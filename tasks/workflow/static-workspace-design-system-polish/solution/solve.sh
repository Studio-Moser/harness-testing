#!/usr/bin/env sh
set -eu
cd /app
cat > 'Styles.css' <<'FIXTURE_EOF'
* { box-sizing: border-box; }
body { margin: 0; font: 16px/1.55 system-ui,sans-serif; color: #213247; background: #f4f6f8; }
.shell { display:grid; grid-template-columns: 230px minmax(0,1fr); min-height:100vh; }
nav { padding:24px 16px; background:#fff; border-right:1px solid #cbd5df; display:flex; flex-direction:column; gap:8px; }
nav strong { margin-bottom:16px; } nav a { min-height:44px; padding:10px 12px; color:#234361; text-decoration:none; border-radius:6px; }
nav a[aria-current] { color:#fff; background:#234361; }
main { min-width:0; padding:40px 32px; max-width:1300px; width:100%; }
header { margin-bottom:28px; } h1 { font-size:34px; line-height:1.2; margin:4px 0 12px; letter-spacing:-.025em; }
h2 { font-size:21px; line-height:1.3; margin:0 0 16px; } h3 { font-size:17px; margin:0 0 6px; } p { margin:0 0 12px; }
.eyebrow { font-size:14px; font-weight:600; } .panel,.cards article { min-width:0; background:#fff; border:1px solid #cbd5df; border-radius:10px; padding:24px; }
button,input,select { min-height:44px; max-width:100%; font:inherit; border:1px solid #6b7d8e; border-radius:5px; padding:8px 12px; color:#213247; background:#fff; }
button { min-width:44px; color:#fff; background:#234361; cursor:pointer; } label { display:block; font-weight:600; }
input,select { display:block; width:100%; margin-top:6px; } :focus-visible { outline:3px solid #996500; outline-offset:3px; }
#status { margin-top:20px; }
@media(max-width:700px) { .shell { grid-template-columns:minmax(0,1fr); } nav { border-right:0; border-bottom:1px solid #cbd5df; } main { padding:28px 20px; } h1 { font-size:28px; } }
FIXTURE_EOF
cat > 'Pages.css' <<'FIXTURE_EOF'
.cards { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:24px; }
.metric { font-size:36px; font-weight:650; line-height:1.2; }
.fields { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:24px; margin-bottom:24px; }
.split { display:grid; grid-template-columns:minmax(0,2fr) minmax(0,1fr); gap:24px; }
.toolbar { display:flex; align-items:end; gap:20px; margin-bottom:20px; } .toolbar label { flex:1; }
.table-scroll { width:100%; overflow-x:auto; } table { width:100%; min-width:620px; border-collapse:collapse; }
td,th { text-align:left; padding:14px 16px; border-bottom:1px solid #cbd5df; } th { background:#eef2f6; }
.timeline { padding:0; margin:0; list-style:none; } .timeline li+li { border-top:1px solid #cbd5df; margin-top:20px; padding-top:20px; }
@media(min-width:701px) and (max-width:1000px) { .cards,.split { grid-template-columns:minmax(0,1fr); } }
@media(max-width:700px) { .cards,.fields,.split { grid-template-columns:minmax(0,1fr); } .toolbar { align-items:stretch; flex-direction:column; } }
FIXTURE_EOF
python Visual_Check.py
