import socket
import struct
import os
import sys
import time
import logging
import configparser
from datetime import datetime
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress
from rich.theme import Theme
import signal

# Configurações de tema para o Rich
custom_theme = Theme({
    "info": "dim cyan",
    "warning": "yellow",
    "error": "bold red",
    "success": "bold green",
    "highlight": "bold blue"
})

console = Console(theme=custom_theme)
running = True  # Variável global para controlar o estado do servidor

class RateLimiter:
    def __init__(self, max_bytes_per_second):
        self.max_bytes_per_second = max_bytes_per_second
        self.last_check = time.time()
        self.bytes_sent = 0

    def limit(self, bytes_to_send):
        current_time = time.time()
        time_passed = current_time - self.last_check
        
        if time_passed >= 1:
            self.bytes_sent = 0
            self.last_check = current_time
        
        if self.bytes_sent + bytes_to_send > self.max_bytes_per_second:
            sleep_time = 1 - time_passed
            time.sleep(sleep_time)
            self.bytes_sent = 0
            self.last_check = time.time()
        
        self.bytes_sent += bytes_to_send

class TFTPStats:
    def __init__(self):
        self.total_bytes_sent = 0
        self.total_bytes_received = 0
        self.successful_transfers = 0
        self.failed_transfers = 0
        self.start_time = datetime.now()

    def get_stats(self):
        uptime = datetime.now() - self.start_time
        return {
            "uptime": str(uptime),
            "bytes_sent": self.format_bytes(self.total_bytes_sent),
            "bytes_received": self.format_bytes(self.total_bytes_received),
            "successful_transfers": self.successful_transfers,
            "failed_transfers": self.failed_transfers
        }

    def format_bytes(self, bytes):
        for unit in ['B', 'KB', 'MB', 'GB']:
            if bytes < 1024:
                return f"{bytes:.2f} {unit}"
            bytes /= 1024
        return f"{bytes:.2f} TB"

    def print_stats(self):
        stats = self.get_stats()
        table = Table(title="Estatísticas do Servidor TFTP")
        table.add_column("Métrica", style="cyan")
        table.add_column("Valor", style="green")
        for key, value in stats.items():
            table.add_row(key.replace('_', ' ').title(), str(value))
        console.print(table)

def setup_logging():
    log_filename = f'tftp_server_{datetime.now().strftime("%Y%m%d")}.log'
    logging.basicConfig(
        filename=log_filename,
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    console.print(f"[info]Logs sendo salvos em: {log_filename}")

def load_config():
    config = configparser.ConfigParser()
    config.read('config.ini')
    
    # Configurações padrão caso não existam no arquivo
    if 'server' not in config:
        config['server'] = {
            'host': '0.0.0.0',
            'port': '69',
            'timeout': '5',
            'max_retries': '3',
            'rate_limit': '1048576'  # 1MB/s
        }
    
    if 'paths' not in config:
        config['paths'] = {
            'safe_directory': './files',
            'allowed_extensions': '.txt,.pdf,.doc,.docx,.jpg,.png'
        }
    
    # Criar diretório seguro se não existir
    if not os.path.exists(config['paths']['safe_directory']):
        os.makedirs(config['paths']['safe_directory'])
    
    return config

def is_allowed_file(filename, allowed_extensions):
    return os.path.splitext(filename)[1].lower() in allowed_extensions

def send_data_with_retry(sock, client_address, block_number, data, max_retries=3):
    for attempt in range(max_retries):
        try:
            packet = struct.pack('!HH', 3, block_number) + data
            sock.sendto(packet, client_address)
            logging.info(f"Enviando bloco {block_number} para {client_address} (tentativa {attempt + 1})")
            
            # Espera ACK
            ack, _ = sock.recvfrom(4)
            ack_block = struct.unpack('!H', ack[2:4])[0]
            if ack_block == block_number:
                return True
            
        except socket.timeout:
            logging.warning(f"Timeout ao enviar bloco {block_number} (tentativa {attempt + 1})")
            console.print(f"[warning]Tentativa {attempt + 1} de {max_retries} falhou. Retransmitindo...")
            continue
    
    return False

def shutdown_server(sock):
    global running
    running = False
    console.print("[warning]Encerrando o servidor TFTP...")
    stats.print_stats()  # Imprime estatísticas finais
    sock.close()
    logging.info("Servidor encerrado")
    console.print("[success]Servidor encerrado com sucesso.")
    sys.exit(0)

def signal_handler(sig, frame):
    console.print("\n[warning]Sinal de interrupção recebido (Ctrl+C).")
    shutdown_server(sock)

def handle_read_request(sock, data, client_address, safe_directory, allowed_extensions, rate_limiter):
    filename = data[2:].split(b'\0')[0].decode()
    file_path = os.path.join(safe_directory, filename)
    
    logging.info(f"Solicitação de leitura recebida para {filename} de {client_address}")
    console.print(f"[info]Solicitação de leitura recebida para o arquivo: [highlight]{filename}[/highlight]")

    if not is_allowed_file(filename, allowed_extensions):
        error_msg = f"Tipo de arquivo não permitido. Extensões permitidas: {', '.join(allowed_extensions)}"
        send_error(sock, client_address, 0, error_msg)
        stats.failed_transfers += 1
        return

    try:
        with open(file_path, 'rb') as file:
            file_size = os.path.getsize(file_path)
            block_number = 1
            bytes_sent = 0
            
            with Progress(transient=True) as progress:
                task = progress.add_task(f"[cyan]Enviando {filename}...", total=file_size)
                
                while True:
                    chunk = file.read(512)
                    if not chunk:
                        break
                    
                    rate_limiter.limit(len(chunk))
                    if not send_data_with_retry(sock, client_address, block_number, chunk):
                        console.print("[error]Falha ao enviar dados após várias tentativas")
                        stats.failed_transfers += 1
                        return
                    
                    bytes_sent += len(chunk)
                    progress.update(task, advance=len(chunk))
                    block_number += 1

            stats.total_bytes_sent += bytes_sent
            stats.successful_transfers += 1
            console.print(f"[success]Arquivo {filename} enviado com sucesso.")
            show_transfer_summary(filename, file_size, client_address, block_number - 1)
            
    except FileNotFoundError:
        send_error(sock, client_address, 1, "Arquivo não encontrado")
        logging.error(f"Arquivo não encontrado: {filename}")
        console.print(f"[error]Arquivo {filename} não encontrado.")
        stats.failed_transfers += 1
    except Exception as e:
        logging.error(f"Erro ao ler arquivo {filename}: {str(e)}")
        console.print(f"[error]Erro ao ler o arquivo: {e}")
        send_error(sock, client_address, 0, "Erro ao ler o arquivo")
        stats.failed_transfers += 1

def handle_write_request(sock, data, client_address, safe_directory, allowed_extensions, rate_limiter):
    filename = data[2:].split(b'\0')[0].decode()
    file_path = os.path.join(safe_directory, filename)
    
    logging.info(f"Solicitação de escrita recebida para {filename} de {client_address}")
    console.print(f"[info]Solicitação de escrita recebida para o arquivo: [highlight]{filename}[/highlight]")

    if not is_allowed_file(filename, allowed_extensions):
        error_msg = f"Tipo de arquivo não permitido. Extensões permitidas: {', '.join(allowed_extensions)}"
        send_error(sock, client_address, 0, error_msg)
        stats.failed_transfers += 1
        return

    try:
        with open(file_path, 'wb') as file:
            block_number = 0
            bytes_received = 0
            
            while True:
                ack = struct.pack('!HH', 4, block_number)
                sock.sendto(ack, client_address)
                
                try:
                    data, _ = sock.recvfrom(516)
                    rate_limiter.limit(len(data))
                except socket.timeout:
                    console.print("[warning]Timeout ao receber dados")
                    continue
                
                opcode = struct.unpack('!H', data[:2])[0]
                if opcode != 3:  # DATA
                    break
                
                block_number = struct.unpack('!H', data[2:4])[0]
                chunk = data[4:]
                file.write(chunk)
                bytes_received += len(chunk)
                
                if len(chunk) < 512:
                    break

            stats.total_bytes_received += bytes_received
            stats.successful_transfers += 1
            console.print(f"[success]Arquivo {filename} recebido com sucesso.")
            show_transfer_summary(filename, bytes_received, client_address, block_number)
            
    except Exception as e:
        logging.error(f"Erro ao escrever arquivo {filename}: {str(e)}")
        console.print(f"[error]Erro ao escrever o arquivo: {e}")
        send_error(sock, client_address, 0, "Erro ao escrever o arquivo")
        stats.failed_transfers += 1

def send_error(sock, client_address, error_code, error_message):
    error_packet = struct.pack('!HH', 5, error_code) + error_message.encode() + b'\0'
    sock.sendto(error_packet, client_address)
    logging.error(f"Erro enviado para {client_address}: {error_message}")
    console.print(f"[error]Enviando erro para {client_address}: {error_message}")

def show_transfer_summary(filename, file_size, client_address, blocks_transferred):
    table = Table(title="Resumo da Transferência", show_header=True, header_style="bold blue")
    table.add_column("Arquivo", style="dim", width=20)
    table.add_column("Tamanho", justify="right", width=15)
    table.add_column("Endereço do Cliente", style="dim", width=25)
    table.add_column("Blocos Transferidos", justify="right", width=10)

    formatted_size = TFTPStats.format_bytes(TFTPStats, file_size)
    table.add_row(filename, formatted_size, str(client_address), str(blocks_transferred))
    console.print(table)

def main():
    global sock, stats
    
    # Inicializar logging
    setup_logging()
    logging.info("Iniciando servidor TFTP")
    
    # Carregar configurações
    config = load_config()
    host = config['server']['host']
    port = int(config['server']['port'])
    timeout = int(config['server']['timeout'])
    max_retries = int(config['server']['max_retries'])
    rate_limit = int(config['server']['rate_limit'])
    safe_directory = config['paths']['safe_directory']
    allowed_extensions = set(config['paths']['allowed_extensions'].split(','))

    # Inicializar componentes
    stats = TFTPStats()
    rate_limiter = RateLimiter(rate_limit)
    
    # Configurar socket
    server_address = (host, port)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)

    # Configurar handlers de sinal
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        sock.bind(server_address)
        console.print(Panel.fit(
            f"[success]Servidor TFTP iniciado em {server_address}[/success]\n"
            f"[info]Diretório de arquivos: {safe_directory}[/info]\n"
            f"[info]Extensões permitidas: {', '.join(allowed_extensions)}[/info]", 
            style="highlight"
        ))
        logging.info(f"Servidor iniciado em {server_address}")
    except OSError as e:
        logging.critical(f"Erro ao iniciar servidor: {str(e)}")
        console.print(f"[error]Erro ao iniciar o servidor em {host}:{port}: {e}")
        sys.exit(1)

    try:
        while running:
            try:
                data, client_address = sock.recvfrom(516)
                opcode = struct.unpack('!H', data[:2])[0]
                
                if opcode == 1:  # RRQ
                    handle_read_request(sock, data, client_address, safe_directory, allowed_extensions, rate_limiter)
                elif opcode == 2:  # WRQ
                    handle_write_request(sock, data, client_address, safe_directory, allowed_extensions, rate_limiter)
                
            except socket.timeout:
                continue
            except Exception as e:
                logging.error(f"Erro inesperado: {str(e)}")
                console.print(f"[error]Erro inesperado: {e}")
                continue
            
    except KeyboardInterrupt:
        console.print("\n[warning]Servidor encerrado pelo usuário.")
        shutdown_server(sock)
    finally:
        sock.close()

if __name__ == "__main__":
    main()
