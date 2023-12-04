import select
import socket
import time
import threading
from _thread import exit
from os import path, remove, replace
from protocol import protocol
from protocol import change_frag_size
from protocol import get_fragment_size


# globals
sequence_number_global = 1


class communication_node():
    """This class is used to create a listener or a sender."""
    def __init__(self, IP_address: str, listening_port: int) -> None:
        self.ustdin = [] # user standard input (Citanie z CLI)
        self.input_running = False

        self.my_IP = IP_address
        self.my_port = listening_port

        self.their_IP = None
        self.their_port = None
        self.connected = False
        self.wants_to_change = False
        self.is_listener = False
        self.is_sender = False

        self.stop_listener = threading.Event()
        self.stop_healthchecker = threading.Event()
        self.stop_sender = threading.Event()
        self.wait_healthchecker = threading.Event()
        self.not_responding = threading.Event()
        self.initialized_termination = threading.Event()

        self.pending_file = threading.Event()
        self.location = ""

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((self.my_IP, self.my_port))

        self.node_main()


    def node_main(self) -> None:
        """ Tato funkcia funguje ako while loop, v ktorom \"existuje\" uzol.
        Nastavuje hodnoty, ktore je potrebne zmit v pripade switchu."""
        while True:
            self.wants_to_change = False

            try:
                remove("buffered_file_temp")
            except FileNotFoundError:
                pass
            self.pending_file.clear()

            self.stop_listener.clear()
            self.stop_healthchecker.clear()
            self.stop_sender.clear()
            self.not_responding.clear()
            self.initialized_termination.clear()

            if not self.connected:
                self.wait_healthchecker.set()

            self.last_healthcheck_sent = 0.0
            self.last_healthcheck_success = 0.0

            if not self.connected:
                user_input = input("Waiting for commands [l, s, d]: ")
            elif self.is_listener:
                user_input = 's'
            else:
                user_input = 'l'

            #listener
            if (user_input == 'l'):
                self.is_listener = True
                self.is_sender = False
                t_listener = threading.Thread(target=self.listener_node, args=[])
                t_listener.start()
            
            #sender
            elif (user_input == 's'):
                self.is_sender = True
                self.is_listener = False
                if not self.connected:
                    self.their_IP = input("Enter reciever IP: ")
                    self.their_port = int(input("Enter reciever port: "))

                t_sender = threading.Thread(target=self.sender_node, args=[self.their_IP, self.their_port])
                t_healthcheck = threading.Thread(target=self.healthcheck, args=[self.their_IP, self.their_port])
                
                t_sender.start()
                t_healthcheck.start()
            
            #exit
            elif (user_input == 'd'):
                self.ustdin = []
                break

            if not self.input_running:
                self.std_input()

            if self.is_listener:
                t_listener.join()
            else:
                t_sender.join()
                t_healthcheck.join()


    def std_input(self) -> None:
        """Hlavne vlakno vstupi do tejto funkcie a spracuva input z CLI."""
        self.input_running = True

        while True:
            stdin = input()
            if self.wants_to_change:
                self.input_running = False
                return

            if stdin == "_QUIT":
                self.__stop_threads()
                self.connected = False
                self.input_running = False
                break
            
            elif stdin.startswith("_SAVE "):
                if self.is_listener:
                    if not self.pending_file.is_set():
                        print("No file has been recieved so far.\n>> ", end='')
                        continue

                    if len(stdin) > 7:
                        self.location = stdin[6:] + ''
                    else:
                        print("No location entered.\n>> ", end='')
                else:
                    print("Not a reciever!")

            elif stdin.startswith("_FRAGMENTSIZE"):
                if self.is_listener:
                    print("Not a sender!")
                else:
                    change_frag_size(stdin[14:])

            elif stdin == "_CHANGE":
                if not self.connected:
                    print("No sender/listener.")
                    continue
                
                self.sock.sendto(protocol(0, "FILE").get_datagram(), (self.their_IP, self.their_port))
                self.wants_to_change = True
                self.input_running = False
                return
            
            elif stdin == "_WHOAMI":
                if self.is_listener:
                    print("You are listener.")
                else:
                    print("You are sender.")
        
            elif self.is_sender:
                self.ustdin.insert(0, stdin)


    def sender_node(self, reciever_UDP_IP: str, reciever_UDP_PORT: int) -> None:
        """Bezi v samostatnom vlakne a predstavuje \'klienta\' v komunikacii."""
        global sequence_number_global
        cin = ""
        send_buffer = b''

        while not self.stop_sender.is_set():
            print("MSG|FILE|NACK|PING|CUSTOM|ERRMSG|ERRFILE\n>>", end='')

            # Kym nie je user input, pocuva odpovede na healthchecky, NACK spravy a poziadavky na switch
            while not len(self.ustdin):
                self.listen_for_healthchecks()

                if self.stop_sender.is_set():
                    exit()
            
            # Caka na typ spravy, ktory sa ma odoslat
            cin = self.__await_input()

            if cin == "MSG" or cin == "ERRMSG":
                message = bytes(self.__await_input("Enter message to send"), "utf8")

                if len(message) > get_fragment_size():
                    send_buffer = message[ get_fragment_size() : ]
                    message = message[ : get_fragment_size() ]
                    send = protocol(sequence_number_global, "MSG", message, 1, 1)
                else:
                    send = protocol(sequence_number_global, "MSG", message)
                
                self.sock.sendto(send.get_datagram(), (reciever_UDP_IP, reciever_UDP_PORT))
            
            elif cin == "FILE" or cin == "ERRFILE":
                filepath = self.__await_input("Enter full path to the file")
                try:
                    file = open(filepath, "rb")
                    filename = path.basename(filepath)
                    file_data = file.read()
                    print("Sending", len(file_data), "B")
                    file_buffer = bytes(filename, "utf8") + bytes('\n', "utf8") + file_data
                    file.close()

                    if len(file_buffer) > get_fragment_size():
                        send_buffer = file_buffer[ get_fragment_size() : ]
                        file_buffer = file_buffer[ : get_fragment_size() ]
                        send = protocol(sequence_number_global, "FILE", file_buffer, 1, 1)
                    else:
                        send = protocol(sequence_number_global, "FILE", file_buffer)
                    
                    self.sock.sendto(send.get_datagram(), (reciever_UDP_IP, reciever_UDP_PORT))
                except FileNotFoundError:
                    print("File not found.")
                    continue

            elif cin == "NACK":
                send = protocol(0, "NACK")
                self.sock.sendto(send.get_datagram(), (reciever_UDP_IP, reciever_UDP_PORT))
                self.initialized_termination.set()
            
            elif cin == "CUSTOM":
                sequence_cust = int(self.__await_input("Sequence number"))
                type_cust = self.__await_input("Message type (only ACK|NACK|MSG|FILE)")
                fragment_cust = int(self.__await_input("Fragment bit (0|1)"))
                first_cust = int(self.__await_input("First bit (0|1)"))
                last_cust = int(self.__await_input("Last bit (0|1)"))
                data_cust = bytes(self.__await_input("Data"), "utf8")
                temp = int(self.__await_input("Checksum (0 to use default)"))
                
                send = protocol(sequence_cust, type_cust, data_cust, fragment_cust, first_cust, last_cust, temp)
                self.sock.sendto(send.get_datagram(), (reciever_UDP_IP, reciever_UDP_PORT))
            
            elif cin == "PING":
                send = protocol(0, "MSG")
                print("Sending healthcheck to remote host.")
                self.sock.sendto(send.get_datagram(), (reciever_UDP_IP, reciever_UDP_PORT))

            else:
                continue

            fragments_sent_total = 1

            # RETRANSMISSION of first datagram
            while cin != "PING":
                if self.stop_sender.is_set():
                    exit()

                # listening for ACK as well as handling retransmissions
                if self.listen_for_ack(reciever_UDP_IP, reciever_UDP_PORT, send, fragments_sent_total):
                    break
                else:
                    exit()
            
            self.connected = True

            # Zapnutie healthcheckera
            if self.wait_healthchecker.is_set():
                self.wait_healthchecker.clear()

            # Pridanie chyby
            if cin.startswith("ERR"):
                error_frag = int(self.__await_input("Error on which fragment (2-2047)?"))
                cin = "MSG" if cin == "ERRMSG" else "FILE"
            else:
                error_frag = -1

            if len(send_buffer) == 0:
                last_frag_size = len(send.data) + 4

            # sending remaining fragments
            while len(send_buffer):
                if self.stop_sender.is_set():
                    exit()
                
                data_to_send = send_buffer[ : get_fragment_size() ]
                send_buffer = send_buffer[ get_fragment_size() : ]
                
                increment_global_sequence()
                if len(send_buffer):
                    send = protocol(sequence_number_global, cin, data_to_send, 1)
                else:
                    send = protocol(sequence_number_global, cin, data_to_send, 1, 0, 1)
                    last_frag_size = len(send.data) + 4
                
                if sequence_number_global == error_frag:
                    bad_send = protocol(sequence_number_global, cin, bytes("AAA", "utf8"), 1, custom_chsum=12)
                    self.sock.sendto(bad_send.get_datagram(), (reciever_UDP_IP, reciever_UDP_PORT))
                    error_frag = -1
                else:
                    self.sock.sendto(send.get_datagram(), (reciever_UDP_IP, reciever_UDP_PORT))
                
                fragments_sent_total += 1
                
                # RETRANSMISSION
                if not self.listen_for_ack(reciever_UDP_IP, reciever_UDP_PORT, send, fragments_sent_total):
                    exit()
            
            increment_global_sequence()
            if fragments_sent_total > 1:
                print("Total fragments sent:", fragments_sent_total,
                    "\nSize of fragments:", get_fragment_size() + 4,
                    "B (Size of the last fragment was", last_frag_size, "B)\n")
            else:
                print("Total fragments sent:", fragments_sent_total,
                    " | Size of the fragment was", last_frag_size, "B\n")

            error_frag = -1
    

    def healthcheck(self, reciever_UDP_IP: str, reciever_UDP_PORT: int) -> None:
        """Bezi v samostatnom vlakne a sluzi na posielanie keep-alive sprav (healthcheck)."""
        while not self.stop_healthchecker.is_set():
            # Posielanie healthcheckov sa da pozastavit
            while self.wait_healthchecker.is_set():
                time.sleep(5)
                if self.stop_healthchecker.is_set():
                    exit()
                continue
            
            counter = 0
            # Ak druha strana dlho neodpoveda na healthcheck
            while self.not_responding.is_set():
                self.sock.sendto(protocol(0, "MSG").get_datagram(), (reciever_UDP_IP, reciever_UDP_PORT))
                counter += 1

                if counter == 11:
                    print("The other side did not respond too long and connection was terminated.")
                    self.__stop_threads()
                    exit()
                
                if self.stop_healthchecker.is_set():
                    exit()
                
                time.sleep(5)
            
            if self.wait_healthchecker.is_set():
                continue

            self.sock.sendto(protocol(0, "MSG").get_datagram(), (reciever_UDP_IP, reciever_UDP_PORT))
            self.last_healthcheck_sent = time.time()
            time.sleep(5)
        
    
    def listen_for_ack(self, reciever_UDP_IP: str, reciever_UDP_PORT: int, send: protocol, total_frags: int) -> bool:
        """Prijimac pre klienta, ktory je schopny znova odoslat zle prijaty/neprijaty fragment."""
        retransmission_count = 0
        time_start = time.time()

        while True:
            if self.stop_sender.is_set():
                exit()

            ready, _, _ = select.select([self.sock], [], [], 0.5)

            if ready:    
                try:
                    client_data, client_address = self.sock.recvfrom(1024)
                except ConnectionResetError: # aby nezachytaval vlastne packety
                    continue

                recieve_protocol = protocol(0, '', read_bytes=client_data)

                # recieving ACK to healthcheck
                if (recieve_protocol.sequence == 0 and recieve_protocol.data_type == "ACK"):
                    #print("Received ACK on healthcheck...")
                    self.last_healthcheck_success = time.time()
                    if self.not_responding.is_set():
                        print("\nConnection reestablished")
                        self.not_responding.clear()
                
                # Not Acknowledge in case of closing the connection
                elif (recieve_protocol.sequence == 0 and recieve_protocol.data_type == "NACK"):
                    if self.initialized_termination.is_set():
                        print("Successfuly terminated connection.")
                        self.__stop_threads()
                        break
                    else:
                        print("Client terminated connection.\n")
                        self.sock.sendto(protocol(0, "NACK").get_datagram(), client_address)
                        self.__stop_threads()
                        break
                
                # handling NACK
                elif (recieve_protocol.data_type == "NACK"):
                    # Preposle fragment znova okamzite
                    print("Retransmitting", send.sequence)
                    self.sock.sendto(send.get_datagram(), (reciever_UDP_IP, reciever_UDP_PORT))
                    retransmission_count += 1
                    total_frags += 1
                    if retransmission_count == 10:
                        self.__stop_threads()
                        print("Retransmit Limit reached for", send.sequence, "\nTerminating connection...")
                        return False
                
                    time_start = time.time()
                
                # ACK to sent data
                elif (recieve_protocol.data_type == "ACK"):
                    #print("Recieved ACK on", recieve_protocol.sequence)
                    if get_global_sequence() == recieve_protocol.sequence:
                        return True
            
            if elapsed_time_seconds(time_start) > 4:
                print("Retransmitting", send.sequence)
                self.sock.sendto(send.get_datagram(), (reciever_UDP_IP, reciever_UDP_PORT))
                retransmission_count += 1
                total_frags += 1

                if retransmission_count == 10:
                    self.__stop_threads()
                    print("Retransmit Limit reached for", send.sequence, "\nTerminating connection...")
                    return False
                
                time_start = time.time()
    
    
    def listen_for_healthchecks(self) -> None:
        """Prijimac pre klienta"""
        ready, _, _ = select.select([self.sock], [], [], 0.5)

        if not self.not_responding.is_set() and not self.stop_sender.is_set():
            if (self.last_healthcheck_success != 0 and elapsed_time_seconds(self.last_healthcheck_success) > 10
                and not self.wait_healthchecker.is_set()):
                print("\nAttempting reconnection...")
                self.not_responding.set()
        
        if ready:
            try:
                client_data, client_address = self.sock.recvfrom(1024)
            except ConnectionResetError: # aby nezachytaval vlastne packety
                return

            recieve_protocol = protocol(0, '', read_bytes=client_data)
            
            # recieving ACK to healthcheck
            if (recieve_protocol.sequence == 0 and recieve_protocol.data_type == "ACK"):
                if self.wants_to_change:
                    self.__stop_threads()
                    print("Changing to listener.")
                    self.wants_to_change = True
                    exit()
                
                #print("Received ACK on healthcheck...")
                self.last_healthcheck_success = time.time()
                if self.not_responding.is_set():
                    print("\nConnection reestablished.")
                    self.not_responding.clear()
            
            # Not Acknowledge in case of closing the connection
            elif (recieve_protocol.sequence == 0 and recieve_protocol.data_type == "NACK"):
                if self.initialized_termination.is_set():
                    print("Successfuly terminated connection.")
                    self.__stop_threads()
                    return
                else:
                    print("Client terminated connection.\n")
                    self.sock.sendto(protocol(0, "NACK").get_datagram(), client_address)
                    self.__stop_threads()
                    return
            
            elif (recieve_protocol.sequence == 0 and recieve_protocol.data_type == "FILE"):
                print("The listener asked to become sender (Press ENTER to continue).")
                self.sock.sendto(protocol(0, "ACK").get_datagram(), client_address)
                self.__stop_threads()
                self.wants_to_change = True


    def listener_node(self) -> None:
        """Bezi v samostatnom vlakne, predstavuje \'server\'"""
        message_buffer = b''
        file_buffer = b''
        fragment_length = 0
        num_of_fragments_recieved = 0
        fragments_await = False

        self.last_healthcheck_success = time.time()
        
        client_address = [0,0]
        while not self.stop_listener.is_set():
            ready, _, _ = select.select([self.sock], [], [], 0.5)

            #prerusenie spojenia ak je iba listener
            if elapsed_time_seconds(self.last_healthcheck_success) > 20:
                self.last_healthcheck_success += 20
                print("\nNo healthcheck recieved for 20 seconds. Type _QUIT to terminate session.")

            if ready:
                try:
                    client_data, client_address = self.sock.recvfrom(1600)
                except ConnectionResetError: # aby nezachytaval vlastne packety
                    continue

                recieve_protocol = protocol(0, '', read_bytes=client_data)

                # priradenie adresy
                if self.connected == False:
                    self.their_IP = client_address[0]
                    self.their_port = client_address[1]
                    self.connected = True

                # checksum didnt add up
                if recieve_protocol.data_type is None:
                    print("Data recieved were corrupted (sequence", recieve_protocol.sequence,
                          "). Asking for retransmission.\n")
                    self.sock.sendto(protocol(recieve_protocol.sequence, "NACK").get_datagram(), client_address)
                
                # recieving healthcheck
                elif (recieve_protocol.sequence == 0 and recieve_protocol.data_type == "MSG"):
                    #print("Recieved Healthcheck...")
                    self.sock.sendto(protocol(0, "ACK").get_datagram(), client_address)
                    self.last_healthcheck_success = time.time()
                    if self.not_responding.is_set():
                        print("\nConnection reestablished")
                        self.wait_healthchecker.set()
                        self.not_responding.clear()
                
                # recieving ACK to healthcheck OR APPROVED CHANGE
                elif (recieve_protocol.sequence == 0 and recieve_protocol.data_type == "ACK"):
                    if self.wants_to_change:
                        self.wants_to_change = False
                        self.__stop_threads()
                        print("Changing to sender.")
                        break
                    
                    #print("Received ACK on healthcheck...")
                    self.last_healthcheck_success = time.time()
                    if self.not_responding.is_set():
                        print("\nConnection reestablished.")
                        self.not_responding.clear()
                
                # Not Acknowledge in case of closing the connection
                elif (recieve_protocol.sequence == 0 and recieve_protocol.data_type == "NACK"):
                    if self.initialized_termination.is_set():
                        print("Successfuly terminated connection.")
                        self.__stop_threads()
                        break
                    else:
                        print("Client terminated connection.\n")
                        self.sock.sendto(protocol(0, "NACK").get_datagram(), client_address)
                        self.__stop_threads()
                        break
                
                #Typ FILE a sequence 0 znamena, ze sa chce 'prepnut'
                elif (recieve_protocol.sequence == 0 and recieve_protocol.data_type == "FILE"):
                    print("Sender wants to become listener (Press ENTER to continue).")
                    self.sock.sendto(protocol(0, "ACK").get_datagram(), client_address)
                    self.__stop_threads()
                    self.wants_to_change = True
                    break

                # recieving file
                elif (recieve_protocol.data_type == "FILE"):
                    # Pripravi sa na to, ze sa budu prichadzat fragmentovane data
                    if recieve_protocol.first_fragment:
                        file_buffer = b''
                        num_of_fragments_recieved = 0
                        last_frag_num = recieve_protocol.sequence
                        fragments_await = True
                    
                    elif fragments_await :
                        # Nesedi sequence number, alebo uz prijal tieto data
                        if (recieve_protocol.sequence <= last_frag_num and last_frag_num != 2047 and recieve_protocol.sequence != 1):
                            self.sock.sendto(protocol(recieve_protocol.sequence, "ACK").get_datagram(), client_address)
                            continue
                        last_frag_num = recieve_protocol.sequence


                    if not fragments_await and recieve_protocol.fragmented:
                        self.sock.sendto(protocol(recieve_protocol.sequence, "NACK").get_datagram(), client_address)
                        continue


                    file_buffer += recieve_protocol.data
                    self.sock.sendto(protocol(recieve_protocol.sequence, "ACK").get_datagram(), client_address)
                    num_of_fragments_recieved += 1

                    if fragment_length == 0:
                        fragment_length = len(recieve_protocol.data) + 4

                    if(recieve_protocol.last_fragment and fragments_await or not recieve_protocol.fragmented):
                        last_frag_size = len(recieve_protocol.data) + 4
                        self.__file_recieved(file_buffer, num_of_fragments_recieved, fragment_length, last_frag_size)
                        file_buffer = b''
                        num_of_fragments_recieved = 0
                        fragment_length = 0
                        fragments_await = False
                
                # recieving text message
                elif (recieve_protocol.data_type == "MSG"):
                    # Pripravi sa na to, ze sa budu prichadzat fragmentovane data
                    if recieve_protocol.first_fragment:
                        message_buffer = b''
                        num_of_fragments_recieved = 0
                        last_frag_num = recieve_protocol.sequence
                        fragments_await = True
                    
                    elif fragments_await :
                        # Nesedi sequence number, alebo uz prijal tieto data
                        if (recieve_protocol.sequence <= last_frag_num and last_frag_num != 2047 and recieve_protocol.sequence != 1):
                            self.sock.sendto(protocol(recieve_protocol.sequence, "ACK").get_datagram(), client_address)
                            continue
                        last_frag_num = recieve_protocol.sequence
                    

                    message_buffer += recieve_protocol.data
                    self.sock.sendto(protocol(recieve_protocol.sequence, "ACK").get_datagram(), client_address)
                    num_of_fragments_recieved += 1
                    
                    if fragment_length == 0:
                        fragment_length = len(recieve_protocol.data) + 4

                    if(recieve_protocol.last_fragment and fragments_await or not recieve_protocol.fragmented):
                        print("\nRecieving from:", client_address[0], "on port:", client_address[1],
                            "\nFragments recieved:", num_of_fragments_recieved, " | Total bytes:", len(message_buffer),
                            "(payload only)\nSize of fragments:", fragment_length, "B (Size of the last fragment was",
                            len(recieve_protocol.data) + 4, "B)\nData:\n", message_buffer.decode("utf8"), "\n")
                    
                        message_buffer = b''
                        num_of_fragments_recieved = 0
                        fragment_length = 0
                        fragments_await = False
                
                # ACK to sent data
                elif (recieve_protocol.data_type == "ACK"):
                    print("Recieved ACK on", recieve_protocol.sequence)
    

    def __await_input(self, message = "") -> str:
        print(message, "\n>> ", sep='', end='')

        while True:
            if len(self.ustdin):
                out = self.ustdin[0]
                self.ustdin.pop(0)
                return out

            time.sleep(0.2)


    def __file_recieved(self, file_buffer: bytes, num_of_fragments_recieved: int, frag_size: int, last_frag_size: int) -> None:
        """Spracuje prijate udaje a vytvori docasny subor s nazvom \'buffered_file_temp\'."""
        print("Recieved file: ", num_of_fragments_recieved, " fragments; ",
              len(file_buffer), " bytes recieved (payload only)\nFragment size: ", frag_size, 
              " B (Last fragment was ", last_frag_size, " B)", sep='')

        splitted_data = file_buffer.split(b'\n', 1)
        filename = splitted_data[0].decode("utf8")
        file_buffer = splitted_data[1]

        file = open("buffered_file_temp", "wb")
        file.write(file_buffer)
        file.close()

        # spusti thread pre citanie z CLI
        self.pending_file.set()
        t_file_handler = threading.Thread(target=self.__file_save, args=[filename])
        t_file_handler.start()


    def __file_save(self, filename: str) -> None:
        """Bezi v samostatnom vlakne a prijaty subor presunie na miesto urcene pouzivatelom."""

        while True:
            print("Where to save it? Its file name was", filename,
                  "\n>> ", end='')
            while len(self.location) == 0:
                time.sleep(1)
                if self.stop_listener.is_set():
                    try:
                        remove("buffered_file_temp")
                    except FileNotFoundError:
                        pass
                    exit()

            try:
                replace("buffered_file_temp", self.location)
                break
            except:
                print("Invalid location")
        
        print("File saved, it's location is \"", self.location, '\"', sep='')
        self.location = ''
        self.pending_file.clear()
        exit()
    

    def __stop_threads(self) -> None:
        """Posle signal vsetkym vlaknam, aby sa ukoncili."""
        if not self.stop_listener.is_set():
            self.stop_listener.set()
        if not self.stop_healthchecker.is_set():
            self.stop_healthchecker.set()
        if not self.stop_sender.is_set():
            self.stop_sender.set()
        if self.not_responding.is_set():
            self.not_responding.clear()



def increment_global_sequence() -> None:
    global sequence_number_global
    sequence_number_global = sequence_number_global + 1 if sequence_number_global < 2047 else 1


def get_global_sequence() -> int:
    global sequence_number_global
    return sequence_number_global


def elapsed_time_seconds(start: float) -> float:
    return time.time() - start
