#!/usr/bin/env python3
"""Build the cheat-sheet poster: animated GIF (1080x1350 -> 810x1012) + static PNG.

Deterministic: the step is passed in the URL (?i=N), the page renders that state
with no timers, and headless Chrome screenshots it. No browser session needed.

    python3 tools/build_poster.py

Outputs:
    assets/cheatsheet.png   1080x1350 static card (LinkedIn / Bluesky)
    assets/cheatsheet.gif   animated reveal, 810x1012, looped (X / anywhere GIFs play)
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ASSETS = os.path.join(ROOT, "assets")
BUILD = os.path.join(ROOT, ".build")
CHROME = shutil.which("google-chrome") or shutil.which("chromium") or "google-chrome"

W, H = 1080, 1350
OUT_W, OUT_H = 810, 1012
STEPS = 12                      # step index 0..STEPS-1

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  html, body { width: 1080px; height: 1350px; overflow: hidden; }
  body {
    font-family: Inter, "DejaVu Sans", sans-serif;
    background: #F4F8FD; color: #0D212B; padding: 34px 44px 30px;
    display: flex; flex-direction: column; gap: 14px;
  }
  .kicker {
    font-size: 20px; font-weight: 700; letter-spacing: 3.4px; text-transform: uppercase;
    color: #0D212B; opacity: .58; display: flex; align-items: center; gap: 14px;
  }
  .kicker:before { content: ""; width: 46px; height: 6px; background: #F1C24C; border-radius: 3px; }
  h1 { font-size: 55px; line-height: 1.06; font-weight: 800; letter-spacing: -1.4px; }
  h1 em { font-style: normal; color: #01C1FC; }
  .sub { font-size: 25px; line-height: 1.32; font-weight: 500; color: #24404d; }
  .stats { display: flex; gap: 14px; }
  .stat {
    flex: 1 1 0; background: #fff; border: 2px solid #dbe6f2; border-radius: 20px;
    padding: 16px 18px 18px; display: flex; flex-direction: column; gap: 6px;
  }
  .stat b { font-size: 37px; font-weight: 800; letter-spacing: -1px; line-height: 1; }
  .stat span { font-size: 17px; line-height: 1.26; font-weight: 500; color: #45606d; }
  .stat.hot { background: #0D212B; border-color: #0D212B; }
  .stat.hot b { color: #F1C24C; }
  .stat.hot span { color: #b9cbd6; }
  .cols { display: flex; gap: 16px; }
  .col {
    flex: 1 1 0; background: #fff; border: 2px solid #dbe6f2; border-radius: 20px;
    padding: 20px 22px 22px;
  }
  .col h2 {
    font-size: 20px; font-weight: 800; letter-spacing: 2.6px; text-transform: uppercase;
    margin-bottom: 12px; display: flex; align-items: center; gap: 10px;
  }
  .col h2 i { width: 13px; height: 13px; border-radius: 4px; display: inline-block; }
  .go h2 { color: #0b7a52; }  .go h2 i { background: #12b76a; }
  .no h2 { color: #b42318; }  .no h2 i { background: #f04438; }
  .col ul { list-style: none; display: flex; flex-direction: column; gap: 11px; }
  .col li { font-size: 20px; line-height: 1.28; font-weight: 500; padding-left: 22px; position: relative; }
  .col li:before { content: ""; position: absolute; left: 0; top: 9px; width: 9px; height: 9px; border-radius: 50%; }
  .go li:before { background: #12b76a; }
  .no li:before { background: #f04438; }
  .shapes { background: #fff; border: 2px solid #dbe6f2; border-radius: 20px; padding: 18px 22px 20px; }
  .shapes h2 {
    font-size: 20px; font-weight: 800; letter-spacing: 2.6px; text-transform: uppercase; margin-bottom: 12px;
  }
  table { width: 100%; border-collapse: collapse; }
  td { font-size: 19px; line-height: 1.24; padding: 8px 0; border-top: 2px solid #eef3f9; vertical-align: middle; }
  tr:first-child td { border-top: 0; }
  td.shape { font-weight: 700; }
  td.rt { text-align: center; font-weight: 800; width: 132px; color: #45606d; }
  td.res { width: 258px; font-weight: 700; }
  .bad { color: #b42318; } .good { color: #0b7a52; }
  code { font-family: "DejaVu Sans Mono", monospace; font-size: 19px; background: #eef3f9; padding: 2px 7px; border-radius: 6px; }
  .traps {
    background: #fff; border: 2px solid #dbe6f2; border-radius: 20px; padding: 18px 22px 20px;
  }
  .traps h2 { font-size: 20px; font-weight: 800; letter-spacing: 2.6px; text-transform: uppercase; margin-bottom: 12px; }
  .chips { display: flex; gap: 12px; }
  .chip {
    flex: 1 1 0; background: #fdf3dd; border: 2px solid #f1c24c; border-radius: 14px;
    padding: 12px 14px; font-size: 19px; line-height: 1.3; font-weight: 600;
  }
  .footer {
    margin-top: auto; display: flex; align-items: center; justify-content: space-between;
    border-top: 4px solid #0D212B; padding-top: 16px;
  }
  .footer b { font-size: 30px; font-weight: 800; letter-spacing: -.4px; }
  .footer span { font-size: 22px; font-weight: 600; color: #45606d; }
  .reveal { opacity: 0; transform: translateY(10px); transition: none; }
  .reveal.in { opacity: 1; transform: none; }
  .ring { box-shadow: 0 0 0 4px #F1C24C, 0 12px 26px rgba(13,33,43,.10) !important; }
</style></head><body>
  <div class="kicker reveal" id="k">Field notes &middot; decision layer</div>
  <h1 class="reveal" id="h">Your AI stack already makes decisions. <em>Give them numbers.</em></h1>
  <div class="sub reveal" id="s">A typed decision layer returns a label and a probability instead of a
    paragraph you have to parse. Same answers, one twentieth of the cost, every time.</div>
  <div class="stats">
    <div class="stat reveal" id="st1"><b>0.74s</b><span>per decision &mdash; against 17.15s for a reasoning chat model</span></div>
    <div class="stat reveal" id="st2"><b>18&times;</b><span>fewer output tokens than a reasoning chat model, same items</span></div>
    <div class="stat reveal hot" id="st3"><b>same</b><span>accuracy: 11/12 vs 11/12. The win is the interface, not the brain.</span></div>
  </div>
  <div class="cols">
    <div class="col go reveal" id="c1"><h2><i></i>Use it when</h2><ul>
      <li>A fork with a fixed label set: one queue, one wave, one intent</li>
      <li>Volume &mdash; cron sweeps, inbound floods, nightly rescoring</li>
      <li>You need a number to threshold, escalate and audit</li>
      <li>Many small judgments about ONE item, in one call</li>
    </ul></div>
    <div class="col no reveal" id="c2"><h2><i></i>Skip it when</h2><ul>
      <li>The output is prose for a human to read</li>
      <li>The candidate list is the real problem, not the decision</li>
      <li>An irreversible action hangs on one probability</li>
    </ul></div>
  </div>
  <div class="shapes reveal" id="sh"><h2>How you batch decides if it works</h2>
    <table>
      <tr><td class="shape">Many <b>items</b> in one state</td><td class="rt">1</td>
          <td class="res bad">probs hedge to 0.33 &mdash; 3/12</td></tr>
      <tr><td class="shape">One <b>item</b> per call, questions inside</td><td class="rt">1/item</td>
          <td class="res good">sharp 0.99 &mdash; 11/12</td></tr>
      <tr><td class="shape">Batching <b>questions</b> about one item</td><td class="rt">1</td>
          <td class="res good">2.76&times; faster &mdash; free</td></tr>
    </table>
  </div>
  <div class="traps reveal" id="tr"><h2>Three traps we hit so you don't</h2>
    <div class="chips">
      <div class="chip">Mega-batching many items into one state</div>
      <div class="chip">Shuffling the candidate order &mdash; 30% of picks flipped</div>
      <div class="chip">Swapping the answerer, then trusting the old thresholds</div>
    </div>
  </div>
  <div class="footer reveal" id="f"><b>One state per call. Then threshold.</b>
    <span>github.com/Amz34/typed-decision-layer</span></div>
<script>
  var ORDER = ["k","h","s","st1","st2","st3","c1","c2","sh","tr","f"];
  var q = new URLSearchParams(location.search);
  var step = q.get("i") === null ? ORDER.length : parseInt(q.get("i"), 10);
  for (var i = 0; i < ORDER.length; i++) {
    var el = document.getElementById(ORDER[i]);
    if (i <= step) { el.classList.add("in"); } else { el.classList.remove("in"); }
  }
  var ringFor = {2:"st1",3:"st2",4:"st3",5:"c1",6:"c2",7:"sh",8:"tr",9:"tr",10:"f"};
  if (ringFor[step]) { document.getElementById(ringFor[step]).classList.add("ring"); }
</script></body></html>
"""


def shoot(html_path: str, step: int, out: str) -> None:
    url = "file://%s?i=%d" % (html_path, step)
    cmd = [
        CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-sandbox",
        "--force-device-scale-factor=1", "--window-size=%d,%d" % (W, H),
        "--virtual-time-budget=900", "--screenshot=" + out, url,
    ]
    run = subprocess.run(cmd, capture_output=True, text=True)
    noise = "dbus" , "DBus", "UPower", "GPU", "gl_surface"
    err = "\n".join(l for l in (run.stderr or "").splitlines() if not any(n in l for n in noise))
    if not os.path.exists(out):
        print(err[-1200:])
        raise SystemExit(f"chrome produced no screenshot for step {step}")


def main() -> int:
    os.makedirs(ASSETS, exist_ok=True)
    os.makedirs(BUILD, exist_ok=True)
    html_path = os.path.join(BUILD, "poster.html")
    with open(html_path, "w", encoding="utf-8") as handle:
        handle.write(PAGE)

    frames = []
    for step in range(STEPS):
        path = os.path.join(BUILD, f"frame_{step:02d}.png")
        shoot(html_path, step, path)
        frames.append(path)
        print(f"step {step:02d} -> {os.path.basename(path)}")

    # static card = final state, full resolution
    final_png = os.path.join(ASSETS, "cheatsheet.png")
    shutil.copyfile(frames[-1], final_png)
    print(f"static  -> {final_png} ({os.path.getsize(final_png) // 1024} KB)")

    # dedupe consecutive identical frames (hash a small downscale)
    keep, seen = [], None
    for path in frames:
        with Image.open(path) as im:
            digest = hashlib.sha256(im.convert("RGB").resize((80, 100)).tobytes()).hexdigest()
        if digest != seen:
            keep.append(path)
            seen = digest
    print(f"gif frames: {len(frames)} -> {len(keep)} after dedupe")

    gif_frames = []
    for path in keep:
        with Image.open(path) as im:
            small = im.convert("RGB").resize((OUT_W, OUT_H), Image.LANCZOS)
        gif_frames.append(small.quantize(colors=128, method=Image.MEDIANCUT, dither=Image.FLOYDSTEINBERG))
    gif_frames[0].save(
        os.path.join(ASSETS, "cheatsheet.gif"),
        save_all=True, append_images=gif_frames[1:], duration=440, loop=0,
        optimize=True, disposal=1,
    )
    gif_path = os.path.join(ASSETS, "cheatsheet.gif")
    print(f"gif     -> {gif_path} ({os.path.getsize(gif_path) // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
