
# Serve-TFTP-em-Python

Este é um servidor TFTP simples implementado em Python. Este projeto utiliza a biblioteca `socket` para comunicação UDP e a biblioteca `rich` para exibir mensagens no terminal de forma estilizada.

## Configuração

Antes de iniciar o servidor, você precisa configurar o arquivo `config.ini`. Este arquivo deve conter as seguintes seções:

```ini
[server]
host = 192.168.0.62
port = 69
timeout = 5

[paths]
safe_directory = C:/tftp
```

### Diretrizes para o `config.ini`:
- **host**: O endereço IP em que o servidor TFTP irá escutar. Certifique-se de que este IP esteja disponível e configurado corretamente.
- **port**: A porta que o servidor irá usar (por padrão, o TFTP usa a porta 69).
- **timeout**: O tempo em segundos que o servidor aguardará por pacotes antes de considerar uma operação como falha.
- **safe_directory**: O diretório onde você deve colocar os arquivos que deseja que os clientes possam acessar.

## Iniciando o Servidor

Para iniciar o servidor, execute o seguinte comando no terminal:

```bash
python seu_script_tftp.py
```

## Problemas Comuns

### O servidor não inicia

Se o servidor não iniciar e você receber uma mensagem de erro relacionada à porta 69, pode haver um processo em execução nessa porta. Para verificar e encerrar o processo, siga as instruções abaixo.

### Verificando Processos na Porta 69

#### No Windows:

1. **Verificar se há serviços usando a porta 69**:
   Abra o **Prompt de Comando** e execute:

   ```cmd
   netstat -aon | findstr :69
   ```

   Isso mostrará todos os processos que estão usando a porta 69. A saída deve ser semelhante a:

   ```
   Proto  Local Address          Foreign Address        State           PID
   UDP    0.0.0.0:69            *:*                                    1234
   ```

   O número na coluna **PID** é o ID do processo.

2. **Identificar o processo**:
   Para descobrir qual processo está usando esse PID, execute:

   ```cmd
   tasklist | findstr 1234
   ```

   Substitua `1234` pelo PID que você encontrou.

3. **Finalizar o processo**:
   Se você determinar que o processo pode ser encerrado, use o seguinte comando para matá-lo:

   ```cmd
   taskkill /F /PID 1234
   ```

   Novamente, substitua `1234` pelo PID correto.

#### No Linux:

1. **Verificar se há serviços usando a porta 69**:
   Abra um terminal e execute:

   ```bash
   sudo netstat -tuln | grep :69
   ```

   Ou você pode usar:

   ```bash
   sudo lsof -i :69
   ```

   Ambos os comandos mostrarão os processos que estão usando a porta 69.

2. **Identificar o processo**:
   Para identificar o PID do processo usando a porta 69, a saída será semelhante a:

   ```
   COMMAND  PID USER   FD   TYPE DEVICE SIZE/OFF NODE NAME
   tftpd    1234 root   4u  IPv4  123456      0t0  UDP *:tftp
   ```

3. **Finalizar o processo**:
   Se você decidir que o processo pode ser encerrado, use o seguinte comando:

   ```bash
   sudo kill -9 1234
   ```

   Novamente, substitua `1234` pelo PID correto.

## Notas Finais

- Certifique-se de ter permissões de administrador para executar o servidor e encerrar processos.
- Para melhor segurança, considere rodar o servidor TFTP em um ambiente isolado ou de teste antes de usá-lo em produção.
