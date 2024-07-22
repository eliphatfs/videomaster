import os
import gzip
import time
import shutil
import argparse
import xml.dom.minidom as xmlp

def text(nodelist):
    rc = []
    for node in nodelist.childNodes:
        if node.nodeType == node.TEXT_NODE:
            rc.append(node.data)
    return ''.join(rc)

argp = argparse.ArgumentParser(
    description="Change premiere sequence time base beyond 60fps.",
    formatter_class=argparse.ArgumentDefaultsHelpFormatter
)
argp.add_argument('in_file', help='input file path')
argp.add_argument('--fps', default=120, help='target fps')
argp.add_argument('--seq_name', default=None, help='target sequence name')
args = argp.parse_args()

kbase = 254016000000
proj = gzip.GzipFile(args.in_file)
# assert len(proj.namelist()) == 1, ["Unknown project format with multiple contents", proj.filelist]
original = proj.read()
uncomp: xmlp.Document = xmlp.parseString(original.decode('utf-8'))
seqs = uncomp.getElementsByTagName("Sequence")
seqs = [seq for seq in seqs if seq.getAttribute('ObjectUID')]
seq_names = [text(seq.getElementsByTagName("Name")[0]) for seq in seqs]
assert len(seqs) > 0, "No sequence found, possibly unsupported project file version"
if args.seq_name is not None:
    sel = seq_names.index(args.seq_name)
elif len(seqs) == 1:
    print("Only one sequence found:", seq_names[0])
    sel = 0
else:
    print("Found sequences:")
    for i, name in enumerate(seq_names):
        print(i, name)
    sel = int(input("Enter index to select: "))
seq: xmlp.Element = seqs[sel]
track_groups = seq.getElementsByTagName("TrackGroup")
target_gid = []
for group in track_groups:
    group: xmlp.Element
    sec = group.getElementsByTagName("Second")
    assert len(sec) == 1, ["Fail to locate track group id from sequence", len(sec)]
    target_gid.append(sec[0].getAttribute('ObjectRef'))
modified = None
for group in uncomp.getElementsByTagName("VideoTrackGroup"):
    if group.getAttribute("ObjectID") in target_gid:
        modified = group.getAttribute("ObjectID")
        print("Located video group.")
        cfps = group.getElementsByTagName("FrameRate")
        assert len(cfps) == 1, ["Fail to locate video frame rate", len(cfps)]
        print("Current: %.3f FPS" % (kbase / int(text(cfps[0]))))
proj.close()
shutil.copyfile(args.in_file, args.in_file + str(int(time.time())) + ".old")
start = original.find(b'<VideoTrackGroup ObjectID="%s"' % modified.encode())
assert start != -1, ['Cannot find replace target', '<VideoTrackGroup ObjectID="%s"' % modified]
start = original.find(b'<FrameRate>', start) + len(b'<FrameRate>')
assert start != -1, ['Cannot find replace target', '<FrameRate>']
end = original.find(b'</FrameRate>', start)
assert end != -1, ['Cannot find replace target', '</FrameRate>']
replaced = original[:start] + str(round(kbase / args.fps)).encode() + original[end:]
proj = gzip.open(args.in_file, "w", compresslevel=6)
proj.write(replaced)
proj.close()
print("Modified to: %.3f FPS" % args.fps)
