import _isolate
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QUndoStack
from fm_video.moodboard_timing import adjusted_frame,timestamp
from fm_video.thumbs import ThumbnailLoader,MoodboardProxyCache
from fm_video.pane import _MoodFrameCommand

APP = QApplication.instance() or QApplication([])


def wait(test):
    until = time.monotonic()+5
    while time.monotonic()<until:
        APP.processEvents()
        if test():
            return True
        time.sleep(.005)
    return False


class MoodboardTimingTest(unittest.TestCase):
    def test_vfr_slider_uses_real_time_and_does_not_cross_neighbors(self):
        times = [0,.01,.02,.03,.04,.05,4.,8.,10.,20.]
        source = SimpleNamespace(frame_count=10,time_of=lambda i:times[i],
                                 index_at_time=lambda t:np.interp(t,times,np.arange(10)))
        self.assertEqual(adjusted_frame(source,[0,3,8],{},3,3,.5),6)
        self.assertEqual(adjusted_frame(source,[0,3,8],{},3,3,-1),1)
        self.assertEqual(adjusted_frame(source,[0,3,8],{},3,3,1),7)
        self.assertEqual(timestamp(3599.9996),'01:00:00.000')

    def test_undo_does_not_repeat_the_initial_commit(self):
        changes = []
        stack = QUndoStack()
        stack.push(_MoodFrameCommand(lambda *args:changes.append(args),2,2,4))
        self.assertEqual(changes,[])
        stack.undo(); stack.redo()
        self.assertEqual(changes,[(2,2),(2,4)])

    def test_one_proxy_only_is_replaced_and_selection_survives_reopening(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as folder:
            path = Path(folder)/'film.mkv'
            path.write_bytes(b'video test')
            source = SimpleNamespace(kind='video',width=160,height=90,frame_count=10,close=lambda:None,
                thumbnail=lambda index,height:np.full((90,160,3),index*20,np.uint8))
            with patch('fm_video.media.open_media',return_value=source), \
                 patch('fm_video.thumbs.video_thumbnail',side_effect=lambda source,index,height:source.thumbnail(index,height)):
                loader = ThumbnailLoader(path,dict(video_moodboard_proxy_width=128),moodboard_proxies=True)
                images,edits = {},[]
                loader.ready.connect(lambda index,image:images.update({index:image}))
                loader.edited.connect(lambda slot,frame,image,final:edits.append((slot,frame,image,final)))
                try:
                    loader.set_moodboard([0,9],(2,1))
                    loader.request([0,9])
                    self.assertTrue(wait(lambda:len(images)==2))
                    cache = MoodboardProxyCache(path,128)
                    before = {i:cache.filename(i).stat().st_mtime_ns for i in (0,9)}
                    loader.edit_frame(0,3,False)
                    self.assertTrue(wait(lambda:bool(edits)))
                    self.assertEqual(before,{i:cache.filename(i).stat().st_mtime_ns for i in (0,9)})
                    loader.edit_frame(0,3,True)
                    self.assertTrue(wait(lambda:any(edit[3] for edit in edits)))
                    self.assertEqual(cache.filename(9).stat().st_mtime_ns,before[9])
                    self.assertNotEqual(cache.filename(0).stat().st_mtime_ns,before[0])
                finally:
                    loader.stop()
                    for thread in loader._threads:
                        thread.join(5)
                reopened = MoodboardProxyCache(path,128)
                self.assertTrue(reopened.prepare([0,9],(2,1)))
                self.assertEqual(reopened.selection,{0:3})
                pixels = reopened.pixels(source,0,90)
                self.assertAlmostEqual(float(pixels.mean()),60,delta=2)
                self.assertEqual(len(list(reopened.directory.glob('*.jpg'))),2)
                saved = json.loads((reopened.directory/'.moodboard_selection.json').read_text())
                self.assertEqual(saved['selection'],{'0':3})

    def test_real_vfr_edit_decodes_the_selected_frame(self):
        from test_video_module import HAS_AV,FFMPEG,make_video,_gray
        from fm_video.media import open_media
        if not HAS_AV or not FFMPEG:
            self.skipTest('PyAV et FFmpeg requis')
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as folder:
            path = Path(folder)/'vfr.mp4'
            make_video(path,count=12,vfr=True)
            source = open_media(path)
            self.assertTrue(source.build_index())
            loader = ThumbnailLoader(path,dict(video_moodboard_proxy_width=128),moodboard_proxies=True,
                                     shared_index=source._index)
            images,edits = {},[]
            loader.ready.connect(lambda index,image:images.update({index:image}))
            loader.edited.connect(lambda slot,frame,image,final:edits.append((slot,frame,image,final)))
            try:
                loader.set_moodboard([0,11],(2,1)); loader.request([0,11])
                self.assertTrue(wait(lambda:len(images)==2))
                loader.edit_frame(0,5,True)
                self.assertTrue(wait(lambda:bool(edits)))
                self.assertEqual(edits[-1][1],5)
                self.assertAlmostEqual(edits[-1][2].pixelColor(2,2).red(),_gray(5),delta=5)
            finally:
                loader.stop()
                for thread in loader._threads:
                    thread.join(5)
                source.close()
