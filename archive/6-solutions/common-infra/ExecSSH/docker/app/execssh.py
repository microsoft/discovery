#!/usr/bin/env python3

import paramiko

# SSH connection details
hostname = "<execution host IP address>"
port = 22
username = "<user ID>"
password = "<user password>"  # or use a private key for better security

# Command to execute
command = "<execution path>/runtool.csh"

# Create SSH client
client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

try:
    client.connect(hostname, port, username, password)
    stdin, stdout, stderr = client.exec_command(command)

    print("Output:")
    print(stdout.read().decode())

    print("Errors:")
    print(stderr.read().decode())

finally:
    client.close()
