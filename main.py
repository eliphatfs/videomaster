import os
import ast
import queue
import argparse
import threading
import fractions
import tqdm
import numpy
import ffmpeg


def start_daemon(target):
    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    return thread


def discard_pipe(pipe):

    def _discard():
        for _ in pipe:
            pass

    start_daemon(_discard)


argp = argparse.ArgumentParser(
    "videomaster",
    description="Video master frame blending.",
    formatter_class=argparse.ArgumentDefaultsHelpFormatter
)
argp.add_argument('in_file', help='input file path')
argp.add_argument('-o', '--out_file', default=None)
argp.add_argument('--encoding', default='h264_nvenc', help='output video codec')
argp.add_argument('--compressor', default='p5', help='compressor quality')
argp.add_argument('--video_bitrate', default='30M', help='video output bitrate')
argp.add_argument('--audio_bitrate', default='320K', help='audio output bitrate')
argp.add_argument('--blend', default=[1, 2, 2, 1], type=ast.literal_eval, help='weights of most recent frames to blend (early frames first)')
argp.add_argument('--buffer', default=12, type=int, help='number of buffer frames')
args = argp.parse_args()
if args.out_file is None:
    base, ext = os.path.splitext(args.in_file)
    args.out_file = base + '.master.mp4'
info = ffmpeg.probe(args.in_file)
video_streams = [s for s in info['streams'] if s['codec_type'] == 'video']
audio_streams = [s for s in info['streams'] if s['codec_type'] == 'audio']
assert len(video_streams) == 1, "Only 1 video stream is supported, got %d" % len(video_streams)
width = video_streams[0]['width']
height = video_streams[0]['height']
n_frames = int(video_streams[0]['nb_frames'])
fps = fractions.Fraction(video_streams[0]['r_frame_rate'])

vid_decode = (
    ffmpeg
    .input(args.in_file)
    .output('pipe:', format='rawvideo', pix_fmt='rgb24')
    .run_async(pipe_stdout=True, pipe_stderr=True)
)
discard_pipe(vid_decode.stderr)
streams = [ffmpeg.input(
    'pipe:', format='rawvideo',
    pix_fmt='rgb24', s=f'{width}x{height}',
    r=str(fractions.Fraction(fps / len(args.blend)).limit_denominator(10000))
)]
if len(audio_streams) > 0:
    streams.append(ffmpeg.input(args.in_file).audio)
vid_encode = ffmpeg.output(
    *streams, args.out_file,
    r=str(fractions.Fraction(fps / len(args.blend)).limit_denominator(10000)),
    vcodec=args.encoding, preset=args.compressor,
    video_bitrate=args.video_bitrate,
    audio_bitrate=args.audio_bitrate, f='mp4'
).overwrite_output().run_async(pipe_stdin=True, pipe_stderr=True)
discard_pipe(vid_encode.stderr)

in_q = queue.Queue(args.buffer)
out_q = queue.Queue(args.buffer)

def decode():
    while True:
        in_bytes = vid_decode.stdout.read(width * height * 3)
        if not in_bytes:
            break
        in_q.put(numpy.frombuffer(in_bytes, numpy.uint8).reshape([height, width, 3]))
    in_q.put(None)

def encode():
    while True:
        out = out_q.get()
        if out is None:
            break
        vid_encode.stdin.write(out.astype(numpy.uint8).tobytes())

def process():
    frames = []
    progbar = tqdm.trange(n_frames)
    progbariter = iter(progbar)
    while True:
        next(progbariter, None)
        progbar.set_description("QI %02d QO %02d" % (in_q.qsize(), out_q.qsize()))
        in_obj = in_q.get()
        if in_obj is None:
            break
        frames.append(in_obj)
        if len(frames) == len(args.blend):
            add_buf = None
            mul_buf = numpy.empty(frames[0].shape, numpy.uint16)
            for blend, frame in zip(args.blend, frames):
                if not isinstance(blend, int):
                    raise TypeError("Blend coefficients should be integers")
                if blend == 0:
                    continue
                elif blend == 1:
                    comp = frame
                else:
                    comp = numpy.multiply(frame, blend, out=mul_buf, dtype=mul_buf.dtype)
                if add_buf is None:
                    add_buf = numpy.add(comp, len(frames) // 2, dtype=numpy.uint16)
                else:
                    add_buf += comp
            add_buf //= sum(args.blend)
            out_q.put(add_buf)
            frames.clear()
    out_q.put(None)

start_daemon(decode)
enc_thread = start_daemon(encode)
process()

enc_thread.join()
vid_encode.stdin.close()
vid_decode.wait()
vid_encode.wait()
