import unittest
from http.server import BaseHTTPRequestHandler
from malab.dashboard.__main__ import LocalServer


class ServerTests(unittest.TestCase):
    def test_second_server_cannot_take_the_same_port(self):
        first=LocalServer(('127.0.0.1',0),BaseHTTPRequestHandler)
        try:
            with self.assertRaises(OSError):
                duplicate=LocalServer(first.server_address,BaseHTTPRequestHandler)
                duplicate.server_close()
        finally:first.server_close()


if __name__=='__main__':unittest.main()
