#!/usr/bin/python3
"""
A tool to create an image of a video DVD.

@copyright: 2009 Bastian Blank <waldi@debian.org>
@license: GNU GPL-3
"""
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 3 as
# published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import sys
import logging

from dvdvideo.media import MediaUdf
from dvdvideo.volume import MalformedVolumePartError


class Part(object):
    def __lt__(self, other):
        if isinstance(other, Part):
            if self.begin < other.begin: return True
            return self.end < other.end
        return NotImplemented

    def __repr__(self):
        return '<%s object: begin: %d; end: %d>' % (self.__class__.__name__,
                self.begin,
                self.end,
                )

    def _dump_iter(self, media):
        length = self.end - self.begin
        cur = 0
        while cur < length:
            count = min(512, length - cur)
            r = self._dump_read(media, cur, count)
            if not len(r):
                logging.debug('got eof')
                return
            cur += len(r) // 2048
            yield r

    def _dump_read(self, media, cur, count):
        try:
            return media.read(count)
        except IOError:
            logging.info('Read error at %d, padding with zeroes', self.begin + cur)
            self._dump_seek(media, cur + count)
            return bytes(count * 2048)

    def _dump_seek(self, media, count, **kw):
        media.seek(self.begin + count, **kw)

    def dump(self, media):
        self._dump_seek(media, 0)
        return self._dump_iter(media)


class PartFile(Part):
    def adjust_other(self, other, all):
        if isinstance(other, self.__class__):
            if self.begin <= other.begin and other.end <= self.end:
                logging.debug('Overlap between %r and %r, removing', self, other)
                all.remove(other)
                return True
            if self.begin <= other.begin and other.begin < self.end:
                logging.debug('Partial overlap between %r and %r, adjusting and removing', self, other)
                self.end = other.end
                all.remove(other)
                return True
        return self.adjust_other_special(other, all)

    def adjust_other_special(self, other, all):
        pass

    def adjust_self(self, all):
        if self.begin == self.end:
            logging.debug('Size 0 in %r, removing', self)
            all.remove(self)
            return True

    def check(self, all):
        for other in all:
            if self is other:
                continue
            if (self.begin <= other.begin and other.begin < self.end or
                self.begin < other.end and other.end <= self.end):
                raise RuntimeError('Overlap between %r and %r' % (self, other))


class PartIfo(PartFile):
    def __init__(self, file):
        self.begin = file.location
        self.end = file.location + file.length


class PartIfoVmg(PartIfo):
    def _dump_iter(self, media):
        r = bytearray(self._dump_read(media, 0, 1))
        r[35] = 0
        yield r

        length = self.end - self.begin
        cur = 1
        while cur < length:
            count = min(512, length - cur)
            r = self._dump_read(media, cur, count)
            if not len(r):
                logging.debug('got eof')
                return
            cur += len(r) // 2048
            yield r


class PartIfoVts(PartIfo):
    pass


class PartVob(PartFile):
    def adjust_other_special(self, other, all):
        if isinstance(other, PartIfo):
            if self.begin <= other.begin and other.begin < self.end and self.end <= other.end:
                logging.debug('Overlap between %r and %r, adjusting', self, other)
                self.end = other.begin
                return True

    def _dump_read(self, media, cur, count):
        try:
            return media.read(count, encrypted=True)
        except IOError:
            logging.debug('Read error at %d', self.begin + cur)
            self._dump_seek(media, cur + count)
            return bytes(count * 2048)

    def dump(self, media):
        self._dump_seek(media, 0, start_encrypted=True)
        return self._dump_iter(media)


class PartMenuVob(PartVob):
    def __init__(self, file):
        self.begin = file.location
        self.end = file.location + file.length


class PartTitleVob(PartVob):
    def __init__(self, file):
        self.begin = file[0].location
        file = file[-1]
        self.end = file.location + file.length


class PartMeta(Part):
    def __init__(self, begin, end):
        self.begin, self.end = begin, end


def main(stream, input, output):
    from dvdvideo.utils import ProgressMeter

    media = MediaUdf(input)
    part = media.udf.volume.partitions[0]

    vmg = media.vmg()
    vts = []
    for i in range(1, vmg.ifo.header.number_titlesets + 1):
        try:
            vts.append(media.vts(i))
        except MalformedVolumePartError as e:
            logging.debug('Ignore VTS %d because of errors (%s)', i, e)
            pass

    image_length = part.location + part.length

    progress = ProgressMeter(stream, image_length // 512)

    parts = []
    parts.append(PartIfoVmg(vmg.fileset.ifo))
    if vmg.fileset.menu_vob:
        parts.append(PartMenuVob(vmg.fileset.menu_vob))
    parts.append(PartIfoVmg(vmg.fileset.bup))

    for i in vts:
        parts.append(PartIfoVts(i.fileset.ifo))
        if i.fileset.menu_vob:
            parts.append(PartMenuVob(i.fileset.menu_vob))
        parts.append(PartTitleVob(i.fileset.title_vob))
        if i.bup:
            parts.append(PartIfoVts(i.fileset.bup))

    logging.debug('parts: %r', parts)

    changed = True
    while changed:
        changed = False
        for i in parts:
            if i.adjust_self(parts):
                changed = True
            for j in parts:
                if i is not j:
                    if i.adjust_other(j, parts):
                        changed = True
    for i in parts:
        i.check(parts)

    logging.debug('parts: %r', parts)

    parts_complete = []
    part_end = 0
    while parts:
        cur = parts.pop(0)
        if cur.begin > part_end:
            parts_complete.append(PartMeta(part_end, cur.begin))
        parts_complete.append(cur)
        part_end = cur.end
    parts_complete.append(PartMeta(part_end, image_length))

    logging.debug('overall parts: %r', parts_complete)

    image = open(output, 'wb')

    cur = 0
    for part in parts_complete:
        logging.debug('part: %r', part)

        for r in part.dump(media):
            count_real = len(r) // 2048
            progress.update(count_real // 512)
            cur += count_real
            image.write(r)

        logging.debug('part end, written %d', cur)

if __name__ == '__main__':
    import optparse
    from dvdvideo.utils import ProgressStream

    class OptionParser(optparse.OptionParser):
        def error(self, msg):
            self.exit(2, "%s: %s\n" % (self.get_prog_name(), msg))
        def exit(self, status=0, msg=None):
            if msg:
                sys.stderr.write(msg)
                sys.stderr.write("Try `%s --help' for more information.\n" % self.get_prog_name())
            sys.exit(status)

    optparser = OptionParser('%prog [OPTION]... INPUT OUTPUT')
    optparser.add_option('-d', '--debug', dest='debug', action='store_true')
    options, args = optparser.parse_args()
    if len(args) != 2:
        optparser.error('incorrect number of arguments')

    stream = ProgressStream(sys.stdout)
    logging.basicConfig(level=options.debug and logging.DEBUG or logging.INFO, stream=stream)

    try:
        try:
            main(stream, *args)
        finally:
            stream.clear_meter()
    except KeyboardInterrupt as e:
        logging.warning('Interrupted')
        sys.exit(1)
