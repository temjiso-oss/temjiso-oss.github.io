# TVスワン RGB 切り替え（Raspberry Pi Pico 用、MicroPython）
#
# 記事「TVスワンを RGB 出力にする」の付属プログラムです。
# Copyright (c) 2026 BW
# MIT License で公開します。自由に使い、直し、配ることができます。
# この著作権表示と許諾の文を残してください。無保証です。全文は LICENSE.txt にあります。
# 確認した環境：Raspberry Pi Pico（RP2040）、MicroPython v1.29.0、
#               TVスワンの基板 552KA1401-R30 REVISION:6.0
# 使い方：main.py と、このファイルを、Pico の中にコピーします。
# 注意：ボタン（GP15）での切り替えは、配線しての確認をまだしていません。
#       ボタンをつながなければ、常に RGB になります。
#
# 働き：
#   ・TVスワンの電源が入り、基板がエンコーダーへ初期設定を書き終えるのを待つ
#   ・そのあと、保存してあるモード（RGB か S端子）の設定を I2C で書く
#   ・ボタンを押すたびにモードを入れ替えて保存する
#   ・基板がもう一度設定を書いた場合（リセットなど）は、書き直す
#
# 配線：GP0 = SDA（緑）、GP1 = SCL（黄）、GND（黒）
#       GP15 = ボタン（もう片方は GND）。押している間だけつながるタイプ
# LED ：点灯 = RGB、消灯 = S端子、速い点滅 = 書き込み失敗
from machine import Pin, SoftI2C
import time

ADDR = 0x44  # MSM7654
SDA_PIN = 0
SCL_PIN = 1
BTN_PIN = 15
MODE_FILE = "mode.txt"

# 基板が起動時に書く値は MR1=0x08、CR0=0x01（S端子／コンポジット出力）
# 同期は G に重ねる（CR0=0x41）。RT4K は HD-15 の RGsB で受ける（2026-11-21 に確認）。
WRITES_RGB = (b"\x02\x41", b"\x01\x18")  # CR0: G に同期を重ねる → MR1: RGB 出力
WRITES_SV = (b"\x01\x08", b"\x02\x01")  # MR1: S端子出力 → CR0: 元の値

led = Pin("LED", Pin.OUT)
btn = Pin(BTN_PIN, Pin.IN, Pin.PULL_UP)
_activity = False


def _on_scl(_pin):
    global _activity
    _activity = True


def _release():
    """線を手放して、SCL の動きを見張る。"""
    Pin(SDA_PIN, Pin.IN, None)
    scl = Pin(SCL_PIN, Pin.IN, None)
    scl.irq(_on_scl, Pin.IRQ_FALLING)


def _lines():
    return Pin(SDA_PIN).value(), Pin(SCL_PIN).value()


def load_mode():
    try:
        with open(MODE_FILE) as f:
            return f.read().strip() != "sv"
    except OSError:
        return True  # 既定は RGB


def save_mode(rgb):
    with open(MODE_FILE, "w") as f:
        f.write("rgb" if rgb else "sv")


def write_mode(rgb):
    """設定を書く。成功したら True。"""
    global _activity
    ok = False
    for _ in range(5):
        if _lines() == (1, 1):
            Pin(SCL_PIN).irq(None)
            try:
                i2c = SoftI2C(scl=Pin(SCL_PIN), sda=Pin(SDA_PIN), freq=20000, timeout=50000)
                for w in WRITES_RGB if rgb else WRITES_SV:
                    i2c.writeto(ADDR, w)
                ok = True
            except OSError:
                ok = False
            _release()
            time.sleep_ms(5)
            _activity = False
            if ok:
                break
        time.sleep_ms(200)
    return ok


def _wait_power():
    """両方の線が 0.2 秒つづけて High になるまで待つ（＝TVスワンの電源が入った）。"""
    t0 = None
    while True:
        if _lines() == (1, 1):
            if t0 is None:
                t0 = time.ticks_ms()
            elif time.ticks_diff(time.ticks_ms(), t0) > 200:
                return
        else:
            t0 = None
        time.sleep_ms(10)


def _wait_master(timeout_ms):
    """基板の初期設定の通信が見えるまで待つ。見えなくても timeout_ms で進む。"""
    global _activity
    _activity = False
    t0 = time.ticks_ms()
    while not _activity and time.ticks_diff(time.ticks_ms(), t0) < timeout_ms:
        time.sleep_ms(10)
    time.sleep_ms(500)  # 通信が終わるのを待つ


def _show(rgb, ok):
    if ok:
        led.value(1 if rgb else 0)


def main():
    global _activity
    rgb = load_mode()
    while True:
        led.value(0)
        _release()
        _wait_power()
        _wait_master(8000)
        ok = write_mode(rgb)
        _show(rgb, ok)
        low_since = None
        while True:
            now = time.ticks_ms()
            # 書き込みに失敗しているあいだは速く点滅
            if not ok:
                led.value((now // 100) & 1)
            # ボタン
            if btn.value() == 0:
                time.sleep_ms(30)
                if btn.value() == 0:
                    rgb = not rgb
                    save_mode(rgb)
                    ok = write_mode(rgb)
                    _show(rgb, ok)
                    while btn.value() == 0:
                        time.sleep_ms(10)
                    time.sleep_ms(50)
            # 基板が設定を書き直した（リセットなど）→ こちらも書き直す
            if _activity and _lines() == (1, 1):
                time.sleep_ms(500)
                ok = write_mode(rgb)
                _show(rgb, ok)
            # TVスワンの電源が切れた（Pico が USB で動いているとき）→ 最初から
            if _lines() == (0, 0):
                if low_since is None:
                    low_since = now
                elif time.ticks_diff(now, low_since) > 300:
                    break
            else:
                low_since = None
            time.sleep_ms(10)
