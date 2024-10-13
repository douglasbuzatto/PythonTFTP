import socket
import struct
import os
import sys
import configparser
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

# Carregar as configurações do arquivo config.ini
def load_config():
    config = configparser.ConfigParser()
    config.read('config.ini')
    return config

# Função para encerrar o servidor de forma graciosa
def shutdown_server(sock):
    global running
    running = False
    console.print("[warning]Encerrando o servidor TFTP...")
    sock.close()
    console.print("[success]Servidor encerrado com sucesso.")
    sys.exit(0)

# Manipulador de sinal para capturar Ctrl+C e SIGTERM
def signal_handler(sig, frame):
    console.print("\n[warning]Sinal de interrupção recebido (Ctrl+C).")
    shutdown_server(sock)

def main():
    global sock
    # Carregar configurações do arquivo
    config = load_config()
    host = config['server']['host']
    port = int(config['server']['port'])
    timeout = int(config['server']['timeout'])
    safe_directory = config['paths']['safe_directory']

    server_address = (host, port)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)  # Timeout do servidor

    # Capturar sinais de interrupção (Ctrl+C e SIGTERM)
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Painel de inicialização
    try:
        sock.bind(server_address)
        console.print(Panel.fit(f"[success]Servidor TFTP iniciado em {server_address}[/success]", style="highlight"))
    except OSError as e:
        console.print(f"[error]Erro ao iniciar o servidor em {host}:{port}: {e}")
        sys.exit(1)

    try:
        while running:
            try:
                data, client_address = sock.recvfrom(516)
                opcode = struct.unpack('!H', data[:2])[0]
                
                if opcode == 1:  # RRQ (Read Request)
                    handle_read_request(sock, data, client_address, safe_directory)
                elif opcode == 2:  # WRQ (Write Request)
                    handle_write_request(sock, data, client_address, safe_directory)
            except socket.timeout:
                continue  # Timeout sem atividade, continuar aguardando
    except KeyboardInterrupt:
        console.print("\n[warning]Servidor encerrado pelo usuário.")
        shutdown_server(sock)
    finally:
        sock.close()

def handle_read_request(sock, data, client_address, safe_directory):
    filename = data[2:].split(b'\0')[0].decode()
    file_path = os.path.join(safe_directory, filename)
    
    console.print(f"[info]Solicitação de leitura recebida para o arquivo: [highlight]{filename}[/highlight]")

    try:
        with open(file_path, 'rb') as file:
            file_size = os.path.getsize(file_path)
            block_number = 1
            # Barra de progresso personalizada
            with Progress(transient=True) as progress:
                task = progress.add_task(f"[cyan]Enviando {filename}...", total=file_size)
                while True:
                    chunk = file.read(512)
                    if not chunk:
                        break
                    send_data(sock, client_address, block_number, chunk)
                    progress.update(task, advance=len(chunk))

                    # Espera ACK
                    try:
                        ack, _ = sock.recvfrom(4)
                        ack_block = struct.unpack('!H', ack[2:4])[0]
                        if ack_block != block_number:
                            console.print(f"[error]Erro: Número de bloco {ack_block} não esperado")
                            break
                    except socket.timeout:
                        console.print("[warning]Timeout esperando ACK, reenviando bloco.")
                        continue
                    
                    block_number += 1
            console.print(f"[success]Arquivo {filename} enviado com sucesso.")

            # Mostrar tabela com informações detalhadas
            show_transfer_summary(filename, file_size, client_address, block_number)
    except FileNotFoundError:
        send_error(sock, client_address, 1, "Arquivo não encontrado")
        console.print(f"[error]Arquivo {filename} não encontrado.")
    except Exception as e:
        console.print(f"[error]Erro ao ler o arquivo: {e}")
        send_error(sock, client_address, 0, "Erro ao ler o arquivo")

def handle_write_request(sock, data, client_address, safe_directory):
    filename = data[2:].split(b'\0')[0].decode()
    file_path = os.path.join(safe_directory, filename)
    
    console.print(f"[info]Solicitação de escrita recebida para o arquivo: [highlight]{filename}[/highlight]")

    try:
        with open(file_path, 'wb') as file:
            block_number = 0
            while True:
                ack = struct.pack('!HH', 4, block_number)
                sock.sendto(ack, client_address)
                
                data, _ = sock.recvfrom(516)
                opcode = struct.unpack('!H', data[:2])[0]
                
                if opcode != 3:  # DATA
                    break
                
                block_number = struct.unpack('!H', data[2:4])[0]
                chunk = data[4:]
                file.write(chunk)
                
                if len(chunk) < 512:
                    break
        console.print(f"[success]Arquivo {filename} escrito com sucesso.")
    except Exception as e:
        console.print(f"[error]Erro ao escrever o arquivo: {e}")
        send_error(sock, client_address, 0, "Erro ao escrever o arquivo")

def send_data(sock, client_address, block_number, data):
    packet = struct.pack('!HH', 3, block_number) + data
    sock.sendto(packet, client_address)
    console.print(f"[info]Enviado bloco [highlight]{block_number}[/highlight] para {client_address}")

def send_error(sock, client_address, error_code, error_message):
    error_packet = struct.pack('!HH', 5, error_code) + error_message.encode() + b'\0'
    sock.sendto(error_packet, client_address)
    console.print(f"[error]Enviando erro para {client_address}: {error_message}")

# Exibir tabela com resumo da transferência
def show_transfer_summary(filename, file_size, client_address, blocks_transferred):
    table = Table(title="Resumo da Transferência", show_header=True, header_style="bold blue")
    table.add_column("Arquivo", style="dim", width=20)
    table.add_column("Tamanho", justify="right", width=10)
    table.add_column("Endereço do Cliente", style="dim", width=25)
    table.add_column("Blocos Transferidos", justify="right", width=10)

    table.add_row(filename, f"{file_size} bytes", str(client_address), str(blocks_transferred))
    console.print(table)

if __name__ == "__main__":
    main()
