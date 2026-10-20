"""Bounded image-header metadata for export planning; never decode image pixels."""
import struct
from build_index import dimensions

HEADER_LIMIT = 262144


def _tiff_orientation(data):
    try:
        order = '<' if data[:2] == b'II' else '>' if data[:2] == b'MM' else None
        if not order or struct.unpack_from(order + 'H', data, 2)[0] != 42:
            return 1
        start = struct.unpack_from(order + 'I', data, 4)[0]
        count = struct.unpack_from(order + 'H', data, start)[0]
        for index in range(min(count, 256)):
            offset = start + 2 + 12 * index
            tag, kind, length = struct.unpack_from(order + 'HHI', data, offset)
            if tag == 274 and kind == 3 and length == 1:
                value = struct.unpack_from(order + 'H', data, offset + 8)[0]
                return value if 1 <= value <= 8 else 1
    except (struct.error, IndexError, ValueError):
        pass
    return 1


def _orientation(data):
    if data[:2] == b'\xff\xd8':
        offset = 2
        while offset + 4 <= len(data):
            if data[offset] != 255:
                break
            while offset < len(data) and data[offset] == 255:
                offset += 1
            if offset >= len(data):
                break
            marker = data[offset]
            offset += 1
            if marker in (0xda, 0xd9):
                break
            if marker == 1 or 0xd0 <= marker <= 0xd8:
                continue
            if offset + 2 > len(data):
                break
            length = int.from_bytes(data[offset:offset + 2], 'big')
            if length < 2 or offset + length > len(data):
                break
            payload = data[offset + 2:offset + length]
            if marker == 0xe1 and payload.startswith(b'Exif\0\0'):
                return _tiff_orientation(payload[6:])
            offset += length
    elif data.startswith(b'\x89PNG\r\n\x1a\n'):
        offset = 8
        while offset + 12 <= len(data):
            length = int.from_bytes(data[offset:offset + 4], 'big')
            if offset + 12 + length > len(data):
                break
            kind = data[offset + 4:offset + 8]
            if kind == b'eXIf':
                return _tiff_orientation(data[offset + 8:offset + 8 + length])
            if kind == b'IDAT':
                break
            offset += length + 12
    elif data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        offset = 12
        while offset + 8 <= len(data):
            length = int.from_bytes(data[offset + 4:offset + 8], 'little')
            payload = data[offset + 8:offset + 8 + length]
            if offset + 8 + length > len(data):
                break
            if data[offset:offset + 4] == b'EXIF':
                return _tiff_orientation(payload[6:] if payload.startswith(b'Exif\0\0') else payload)
            offset += 8 + length + (length % 2)
    return 1


def image_metadata(path):
    size = dimensions(path)
    if not size:
        return None
    with open(path, 'rb') as stream:
        orientation = _orientation(stream.read(HEADER_LIMIT))
    width, height = size
    if orientation in (5, 6, 7, 8):
        width, height = height, width
    return {'width': width, 'height': height, 'encodedWidth': size[0],
            'encodedHeight': size[1], 'orientation': orientation,
            'source': 'bounded-header'}
