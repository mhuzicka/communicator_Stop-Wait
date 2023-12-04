# Provides a class protocol, that is used as a protocol on application
# layer for this project. It can create an instance of this protocol
# by simply calling constructor. 

from struct import pack


#globals
fragment_size = 1428


class protocol:
    """This class is a representation of an application protocol used in this project.
    It is used to both create a datagram and to read recieved bytes."""
    polynomial = 0x11021 # CCITT (zapisane aj x^16)


    def __init__(self, Sequence_number: int, Data_type: str,
                 Data = b'', Fragment = 0, First = 0, Last = 0, custom_chsum = 0, read_bytes = b'') -> None:
        global fragment_size

        if read_bytes != b'':
            self.__read_datagram(read_bytes)
            return

        if Data_type == '':
            return

        self.data = Data

        self.sequence = Sequence_number
        self.fragmented = True if Fragment == 1 else False
        self.first_fragment = True if First == 1 else False
        self.last_fragment = True if Last == 1 else False
        
        line1 = Sequence_number << 5 | self.__deduct_type(Data_type) | Fragment << 2 | First << 1 | Last

        if len(Data) == 0:
            self.checksum = 0
            if not custom_chsum:
                self.datagram = pack('>H', line1) + b'\x00\x00'
            else:
                self.datagram = pack('>H', line1) + pack('>H', custom_chsum)
        else:
            if not custom_chsum:
                self.checksum = self.__compute_checksum(pack('>H', line1) + self.data)
                self.datagram = pack('>H', line1) + pack('>H', self.checksum) + self.data
            else:
                self.datagram = pack('>H', line1) + pack('>H', custom_chsum) + self.data


    def __deduct_type(self, Type: str) -> int:
        if Type[0] == 'A': #ACK
            self.data_type = "ACK"
            return 0b10000
        elif Type[0] == 'N': #NACK
            self.data_type = "NACK"
            return 0b11000
        elif Type[0] == 'M': #MSG
            self.data_type = "MSG"
            return 0b00000
        else: #FILE
            self.data_type = "FILE"
            return 0b01000
    

    def __compute_checksum(self, Data: bytes) -> int:
        """Vypocita 16-bitove CRC"""
        number = int.from_bytes(Data, "big") << 16
        data_bits = number.bit_length()
        if data_bits == 0:
            return 0

        divisor = self.polynomial
        divisor <<= data_bits - 17

        while number > 0xffff:
            number = number ^ divisor

            data_bits = number.bit_length()
            div_bits = divisor.bit_length()
            divisor >>= div_bits - data_bits

        return number


    def get_datagram(self) -> bytes:
        """Returns whole datagram (header and data)."""
        return self.datagram
    

    def __read_datagram(self, string: bytes) -> None:
        """Returns an object of protocol class from bytes.

        Returns self.data_type = None if checksum doesn't add up. Only self.sequence is a valid value then."""

        if len(string) > 4 and self.__compute_checksum(string [:2] + string[4:]) != int.from_bytes(string[2:4], "big"):
            self.sequence = int.from_bytes(string[:2], "big") >> 5
            self.data_type = None
            return
        
        self.__read_info(string)


    def __read_info(self, string: bytes) -> None:
        """Ulozi udaje do premennych citatelnych programom."""
        self.checksum = int.from_bytes(string[2:4], "big")

        value_int = int.from_bytes(string[:2], "big")
        self.sequence = value_int >> 5

        self.fragmented = True if (value_int & 0b100) == 4 else False
        self.first_fragment = True if (value_int & 0b010) == 2 else False
        self.last_fragment = True if (value_int & 0b001) == 1 else False

        temp = value_int & 0b11000
        if temp == 0b10000:
            self.data_type = "ACK"
        elif temp == 0b11000:
            self.data_type = "NACK"
        elif temp == 0b00000:
            self.data_type = "MSG"
        else:
            self.data_type = "FILE"

        self.data = string[4:]



def change_frag_size(input: str) -> None:
    """Funkcia sluzi na zmenu velkosti fragmentov pri posielanie. K tomu ma pristup iba vysielac (klient)."""
    global fragment_size

    if len(input) == 0:
        print("Current maximum fragment size is", fragment_size)
        return

    try:
        temp = int(input, base=10)
        if temp > 0 and temp <= 1428:
            fragment_size = temp
            print("Maximum fragment size is now", fragment_size)
        else:
            raise ValueError
    except ValueError:
        print("Invalid Value. Must be between 1 and 1428. Syntax is: _FRAGMENTSIZE 123")


def get_fragment_size() -> int:
    global fragment_size
    return fragment_size
