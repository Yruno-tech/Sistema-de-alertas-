"""Local TLS only. Does not reach the LAN, Google or a phone."""
import json
import socket
import ssl
import threading

from configurar_gateway import create_configuration


def test_generated_certificate_is_trusted_only_for_the_configured_ip(tmp_path):
    create_configuration('192.168.1.5', ['+5493764000001'], tmp_path)
    config = json.loads((tmp_path / 'emparejar-gateway.json').read_text())
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(tmp_path / 'credentials/gateway-server.pem', tmp_path / 'credentials/gateway-server.key')
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen(3)
    listener.settimeout(5)
    port = listener.getsockname()[1]
    results = []

    def serve():
        try:
            for _ in range(3):
                raw, _ = listener.accept()
                try:
                    with server_context.wrap_socket(raw, server_side=True) as conn:
                        conn.sendall(b'OK')
                except ssl.SSLError:
                    results.append('rejected')
        finally:
            listener.close()

    worker = threading.Thread(target=serve, daemon=True)
    worker.start()
    trusted = ssl.create_default_context(cadata=config['certificatePem'])
    with socket.create_connection(('127.0.0.1', port), timeout=3) as raw:
        with trusted.wrap_socket(raw, server_hostname='192.168.1.5') as conn:
            assert conn.recv(2) == b'OK'
    for context, host in [(trusted, '192.168.1.6'), (ssl.create_default_context(), '192.168.1.5')]:
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=3) as raw:
                with context.wrap_socket(raw, server_hostname=host):
                    raise AssertionError('Untrusted or wrong-host certificate accepted')
        except ssl.SSLCertVerificationError:
            pass
    worker.join(timeout=5)
    assert not worker.is_alive()
    assert results == ['rejected', 'rejected']
