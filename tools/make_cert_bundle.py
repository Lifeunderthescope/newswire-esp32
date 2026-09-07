"""Make ESP-IDF 5.5+ compact CA bundle from certifi's Mozilla trust store.

The format is documented by Espressif's gen_crt_bundle.py: sorted DER subjects,
little-endian record offsets followed by subject/public-key records.
"""
from pathlib import Path
import struct
import certifi
from cryptography import x509
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat


def main():
    certs = x509.load_pem_x509_certificates(Path(certifi.where()).read_bytes())
    records = sorted((c.subject.public_bytes(), c.public_key().public_bytes(
        Encoding.DER, PublicFormat.SubjectPublicKeyInfo)) for c in certs)
    offsets, body = [], bytearray()
    for subject, key in records:
        offsets.append(4 * len(records) + len(body))
        body.extend(struct.pack('<HH', len(subject), len(key)) + subject + key)
    bundle = struct.pack(f'<{len(offsets)}I', *offsets) + body
    lines = [', '.join(f'0x{b:02x}' for b in bundle[i:i+16]) for i in range(0, len(bundle), 16)]
    output = Path(__file__).resolve().parents[1] / 'firmware/newswire/cert_bundle.h'
    output.write_text('// Generated from certifi; refresh when updating firmware.\n'
                      '#pragma once\n#include <Arduino.h>\n'
                      'static const uint8_t NEWS_CA_BUNDLE[] PROGMEM = {\n' +
                      ',\n'.join(lines) + '\n};\n', encoding='utf-8')
    print(f'{len(records)} roots, {len(bundle)} bytes -> {output}')
    # HN serves a GTS chain cross-signed by a retired GlobalSign root. The compact
    # ESP bundle callback follows the transmitted chain to that absent issuer.
    # Full PEM trust anchors let mbedTLS terminate at the trusted GTS root instead.
    names = {f'GTS Root R{i}' for i in range(1, 5)}
    google_roots = [c for c in certs if any(
        a.value in names for a in c.subject.get_attributes_for_oid(x509.NameOID.COMMON_NAME))]
    if not any(c.subject.get_attributes_for_oid(x509.NameOID.COMMON_NAME)[0].value == 'GTS Root R1' for c in google_roots):
        raise ValueError('Expected GTS Root R1 in certifi; review trust-store changes')
    pem = ''.join(c.public_bytes(Encoding.PEM).decode('ascii') for c in google_roots)
    output.with_name('hn_roots.h').write_text(
        '// GTS trust anchors from certifi; normal mbedTLS chain validation for HN.\n'
        '#pragma once\n#include <Arduino.h>\n'
        'static const char NEWS_HN_CA_PEM[] PROGMEM = R"NEWSCA(\n' + pem + ')NEWSCA";\n',
        encoding='utf-8')


if __name__ == '__main__':
    main()

