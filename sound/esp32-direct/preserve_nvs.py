"""Prepare factory image while preserving the device's NVS settings."""
from pathlib import Path
import hashlib, struct, os
root=Path('/private/tmp/agentcenter-direct')
original=(root/'pre-flash-16mb.bin').read_bytes()
source=root/'xiaozhi-esp32-2.4.0/build/merged-binary.bin'
merged=bytearray(source.read_bytes())
def partitions(image):
    out={}
    for at in range(0x8000,0x9000,32):
        magic,kind,sub,offset,size,label,flags=struct.unpack('<HBBII16sI',image[at:at+32])
        if magic!=0x50aa:break
        out[label.rstrip(b'\0').decode()] = (kind,sub,offset,size)
    return out
old=partitions(original);new=partitions(merged)
assert len(original)==0x1000000 and 'nvs' in old and 'nvs' in new
old_offset,old_size=old['nvs'][2:];new_offset,new_size=new['nvs'][2:]
assert old_size==new_size, 'NVS migration needs explicit handling for changed partition size'
assert new_offset+new_size<=len(merged)
nvs=original[old_offset:old_offset+old_size]
merged[new_offset:new_offset+new_size]=nvs
assert merged[new_offset:new_offset+new_size]==nvs
output=root/'agentcenter-direct-preserved-nvs.bin';output.write_bytes(merged);os.chmod(output,0o600)
print('Prepared image:',len(merged),'bytes; original NVS preserved:',hex(new_offset),hex(new_size))
print('SHA256:',hashlib.sha256(merged).hexdigest())
