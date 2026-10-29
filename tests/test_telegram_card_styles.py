"""Simulated financial-card checks; never connect to MT5 or Telegram."""
from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw
from server import pnl_cards as cards


class TelegramCardStyleTests(unittest.TestCase):
    def sample(self, **changes):
        row=dict(account_key='SIMULATION | Broker|123',ticket='SIM-501',symbol='XAUUSD.c',
                 direction='SELL',state='OPEN',volume=.001,entry=4160.31,current_price=4158.72,
                 sl=4161.90,tp=4157.20,sl_pnl=-1.59,tp_pnl=3.11,pnl=.93,currency='USC',
                 observed_utc=datetime.now(timezone.utc).isoformat(),strategy='MOMENTUM_SCALP')
        row.update(changes)
        return row

    def test_native_currency_small_volume_and_absent_stop(self):
        self.assertEqual(cards._quantity(.001),'0.001')
        self.assertEqual(cards._stop(0),'Not set')
        self.assertEqual(cards._money(.93,'USC'),'+0.93 USC')
        self.assertEqual(cards._money(.93,'USD'),'+$0.93')
        self.assertEqual(cards._money(None,'USD'),'—')

    def test_missing_pnl_is_not_presented_as_zero(self):
        with patch.object(cards,'_render',return_value=Path('mock.png')) as render:
            cards.render_trade_card(self.sample(pnl=None))
        self.assertEqual(render.call_args.kwargs['headline'],'PnL not available')
        self.assertIn('SIMULATION',render.call_args.kwargs['state'])

    def test_stop_update_observation_and_known_trailing_are_distinct(self):
        with patch.object(cards,'_render',return_value=Path('mock.png')) as render:
            cards.render_stop_update_card(self.sample(old_sl=4161.9,new_sl=4160.5,
                old_sl_pnl=-1.59,new_sl_pnl=-.19))
        self.assertEqual(render.call_args.args[0],'STOP LOSS UPDATED')
        self.assertIn('4,161.90',render.call_args.kwargs['headline'])
        details=dict(render.call_args.args[3])
        self.assertEqual(details['At previous SL'],'−1.59 USC')
        self.assertEqual(details['At new SL'],'−0.19 USC')
        self.assertEqual(details['Floating PnL'],'+0.93 USC')
        with patch.object(cards,'_render',return_value=Path('mock.png')) as render:
            cards.render_stop_update_card(self.sample(old_sl=0,new_sl=4159.5,reason='TRAILING'))
        self.assertEqual(render.call_args.args[0],'TRAILING SL UPDATED')
        self.assertTrue(render.call_args.kwargs['headline'].startswith('Not set'))

    def test_stale_snapshot_and_future_clock_are_identified(self):
        now=datetime.now(timezone.utc)
        self.assertFalse(cards._stale(now.isoformat(),now))
        self.assertTrue(cards._stale((now-timedelta(seconds=61)).isoformat(),now))
        self.assertTrue(cards._stale((now+timedelta(seconds=61)).isoformat(),now))
        self.assertTrue(cards._stale(None,now))

    def test_bounded_long_card_text(self):
        draw=ImageDraw.Draw(Image.new('RGB',(1080,1350)))
        text,font=cards._fit_text(draw,'VERY LONG BROKER SYMBOL '*10000,590,31)
        self.assertLessEqual(draw.textbbox((0,0),text,font=font)[2],590)
        self.assertLess(len(text),513)

    def test_cards_paginate_preserve_templates_and_never_combine_currency(self):
        originals=[cards.asset_path('IMAGES/PnL_CARDS/'+name+'.jpg') for name in ('PROFIT','LOSS')]
        hashes=[hashlib.sha256(path.read_bytes()).digest() for path in originals]
        with tempfile.TemporaryDirectory() as folder:
            outputs=cards.render_positions_cards([self.sample(ticket='SIM-'+str(i),currency='USC' if i%2 else 'USD') for i in range(5)],output_dir=folder)
            self.assertEqual(len(outputs),3)
            outputs.append(cards.render_stop_update_card(self.sample(old_sl=4161.9,new_sl=4160.5),output=Path(folder)/'sl.png'))
            outputs.append(cards.render_trade_card(self.sample(pnl=-.93,state='CLOSED'),output=Path(folder)/'loss.png'))
            for output in outputs:
                with Image.open(output) as image:
                    self.assertEqual((image.format,image.size),('PNG',(1080,1350)))
            for original in originals:
                with self.assertRaises(ValueError):
                    cards.render_trade_card(self.sample(pnl=1),output=original)
        self.assertEqual(hashes,[hashlib.sha256(path.read_bytes()).digest() for path in originals])

    def test_transparent_card_keeps_landscape_brightness(self):
        # Regression: a dark overlay previously covered most of the supplied
        # natural scenery, even though the source templates were preserved.
        from PIL import ImageOps, ImageStat
        for positive, name in ((True, 'PROFIT'), (False, 'LOSS')):
            path = cards.asset_path('IMAGES/PnL_CARDS/' + name + '.jpg')
            with Image.open(path) as original:
                reference = ImageOps.fit(original.convert('RGB'), (1080, 1350),
                                         centering=(.5, .38))
            rendered, _, _ = cards._canvas(positive)
            # Blurring in place cannot make the whole center an opaque black box.
            crop = (130, 360, 950, 980)
            raw_mean = ImageStat.Stat(reference.crop(crop).convert('L')).mean[0]
            rendered_mean = ImageStat.Stat(rendered.crop(crop).convert('L')).mean[0]
            self.assertLess(abs(raw_mean-rendered_mean), 18)
            # Nature outside the information area stays pixel-identical.
            self.assertEqual(reference.getpixel((20, 80)), rendered.getpixel((20, 80)))

    def test_positions_unknown_total_and_stale_marker_remain_truthful(self):
        captured=[]
        original=cards._fit_text
        def capture(draw,text,*args,**kwargs):
            captured.append(str(text))
            return original(draw,text,*args,**kwargs)
        with tempfile.TemporaryDirectory() as folder,patch.object(cards,'_fit_text',side_effect=capture):
            cards.render_positions_cards([self.sample(pnl=None,observed_utc='2026-01-01T00:00:00+00:00')],output_dir=folder)
        self.assertIn('Floating PnL unavailable',captured)
        self.assertTrue(any('STALE SNAPSHOT' in item for item in captured))
        self.assertTrue(any('SIMULATION' in item for item in captured))


if __name__=='__main__':
    unittest.main()
