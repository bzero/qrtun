import qrtools
from pytun import TunTapDevice, IFF_TAP, IFF_TUN, IFF_NO_PI
import base64
import sys
import select
import signal
import sdl2.ext
from sdl2 import SDL_Event, SDL_PollEvent, SDL_QUIT, SDL_KEYDOWN, SDLK_ESCAPE, SDL_SetWindowFullscreen
from sdl2.ext import Color
import ctypes
import os
import cv2
import scipy.misc
SIZE = 1024
window = sdl2.ext.Window("Hello World!", size=(SIZE, SIZE))

factory = sdl2.ext.SpriteFactory(sdl2.ext.SOFTWARE)
spriterenderer = factory.create_sprite_render_system(window)

class QRTun(object):
    def __init__(self, side):
        self.side = int(side)
        if self.side not in [1,2]:
            print("Side must be 1 or 2")
            raise Exception("Invalid Side")
        self.tun = TunTapDevice(flags=IFF_TUN|IFF_NO_PI, name='qrtun%d'%self.side)
        self.tun.addr = '10.0.8.%d'%(self.side)
        if self.side == 1:
            self.other_side = 2
        else:
            self.other_side = 1
        self.tun.netmask = '255.255.255.0'
        #MTU must be set low enough to fit in a single qrcode
        self.tun.mtu = 500
        self.epoll = select.epoll()
        self.epoll.register(self.tun.fileno(), select.EPOLLIN)
        self.tun.up()
        self.outfile = 'resources/toscreen%d.png'%(self.side)
        self.infile = 'resources/toscreen%d.png'%(self.other_side)
        self.indata = None
        self.olddata = ""
        self.outdata = ""
        self.running = False
        self.qr = qrtools.QR()
        self.vc = cv2.VideoCapture(0)
        self.vc.set(cv2.cv.CV_CAP_PROP_FRAME_HEIGHT, 720)
        self.vc.set(cv2.cv.CV_CAP_PROP_FRAME_WIDTH, 1280)
    def read_tun(self):
        events = self.epoll.poll(0)
        if events:
            self.outdata = self.tun.read(self.tun.mtu)
            return True
        return False
    def write_qrcode(self):

        #Could not get binary mode working with qrtool library... so instead opt to
        # use base32 for now, obviously binary would be better.
        #Base32 encode since alphanumeic qr code only allows A-Z, 0-9 and some
        # symbols, but base64 uses lowercase as well....
        #Also alphanumeric mode does not support '=', so replace with '/' and
        # switch back on the other side...
        body = base64.b32encode(self.outdata).replace('=', '/')
        qr = qrtools.QR()
        qrb = qrtools.QR()
        qrb.data = "  "
        qr.data = body

        #Had an issue where decoded data did not match encoded data...
        #So I just add plus symbols as padding until they match, then strip
        # on the other side....
        while qr.data != qrb.data:
            qr.pixel_size = 12
            qr.encode(self.outfile)

            qrb.decode(self.outfile)
            if qrb.data != qr.data:
                print("EncodingFailure", qr.data)
                qr.data += '+'


        self.msg_read = False
    def write_tun(self):
        try:
            if len(self.indata.get('body')) > 0:
                data = self.indata.get('body')
                if data != self.olddata:
                    self.tun.write(data)
                    #This is a hacky way to avoid dup packets...
                    #surely a better way to do this...
                    self.olddata = data
        except:
            print("Failed to write to tun!")
    def read_qrcode(self):
        qr = qrtools.QR()
        try:
            if not qr.decode(self.infile):
                return False

            body   = base64.b32decode(qr.data.replace('/', '=').replace('+', ''))
            self.indata = {'body': body}
            self.write_tun()
        except:
            pass


    def run(self):
        self.running = True
        while self.running:
            if self.read_tun():
                self.write_qrcode()

            rval, frame = self.vc.read()
            if not rval:
                running = False
                break
            scipy.misc.toimage(frame).save(self.infile)
            self.read_qrcode()

            if os.path.isfile(self.outfile):
                sprite = factory.from_image(self.outfile)
                spriterenderer.render(sprite)
            
            event = SDL_Event()
            while SDL_PollEvent(ctypes.byref(event)) != 0:
              if event.type == SDL_QUIT:
                self.running = False
                break
              elif event.type == SDL_KEYDOWN and event.key.keysym.sym == SDLK_ESCAPE:
                self.running = False
                break


        try:
            os.unlink(self.outfile)
            os.unlink(self.infile)
        except:
            pass

def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ['1', '2']:
        print("Must specify side 1 or 2 of tunnel")
        sys.exit(0)
    tun = QRTun(sys.argv[1])
    def signal_handler(signal, frame):
            print('Shutting down')
            tun.running = False
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)




    window.show()

    tun.run()
    sys.exit(0)


if __name__ == "__main__":
    main()
