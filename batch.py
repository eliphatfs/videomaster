import os
import glob
import tqdm
import ffmpeg
from threading import Thread

files = sorted(glob.glob(r"D:\Fish\bvh\subjects/**/*.avi"))
output = r"D:\Fish\bvh\subjects\convert"
multiproc = 4

def start_daemon(target):
    thread = Thread(target=target, daemon=True)
    thread.start()
    return thread


def discard_pipe(pipe):

    def _discard():
        for _ in pipe:
            pass

    start_daemon(_discard)

q = []
for f in tqdm.tqdm(files):
    p = (
        ffmpeg
        .input(f)
        .output(
            os.path.join(output, os.path.basename(f.replace('.avi', '.mp4'))),
            vcodec='h264_nvenc',
            video_bitrate="1M",
            audio_bitrate="96K"
        )
        .run_async(pipe_stdout=True, pipe_stderr=True)
    )
    discard_pipe(p.stdout)
    discard_pipe(p.stderr)
    p.wait()
