from pathlib import Path
import re
import struct
from cryptography import x509

FIRMWARE = Path(__file__).resolve().parents[1] / 'firmware/newswire'


def test_compact_bundle_offsets_and_sort_order():
    data = bytes(int(x, 16) for x in re.findall(r'0x([0-9a-f]{2})',
                 (FIRMWARE / 'cert_bundle.h').read_text()))
    count = struct.unpack_from('<I', data)[0] // 4
    offsets = struct.unpack_from(f'<{count}I', data)
    subjects = []
    for i, offset in enumerate(offsets):
        name_length, key_length = struct.unpack_from('<HH', data, offset)
        end = offset + 4 + name_length + key_length
        assert end == (offsets[i+1] if i+1 < count else len(data))
        subjects.append(data[offset+4:offset+4+name_length])
    assert subjects == sorted(subjects)


def test_hn_has_full_gts_trust_anchors():
    roots = x509.load_pem_x509_certificates((FIRMWARE / 'hn_roots.h').read_bytes())
    names = {root.subject.get_attributes_for_oid(x509.NameOID.COMMON_NAME)[0].value for root in roots}
    assert 'GTS Root R1' in names and names <= {f'GTS Root R{i}' for i in range(1, 5)}
    assert all(root.subject == root.issuer for root in roots)
    assert all(root.extensions.get_extension_for_class(x509.BasicConstraints).value.ca for root in roots)

