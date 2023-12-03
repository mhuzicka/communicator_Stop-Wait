from communication_node import communication_node

# ----- main -----
if __name__ == "__main__":
    ip_addr = input("IP address: ")
    l_port = int(input("Listening port: "))
    usr = communication_node(ip_addr, l_port)
