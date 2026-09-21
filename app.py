from flask import Flask, request, jsonify, send_from_directory, render_template
from pathlib import Path
from urllib.parse import urlparse
from werkzeug.utils import secure_filename
import os,re,uuid,subprocess,threading,time,json,urllib.parse,urllib.request,cv2,pytesseract

BASE=Path(__file__).resolve().parent
UPLOAD=BASE/"storage"/"uploads"; OUTPUT=BASE/"storage"/"outputs"
UPLOAD.mkdir(parents=True,exist_ok=True); OUTPUT.mkdir(parents=True,exist_ok=True)
app=Flask(__name__); app.config["MAX_CONTENT_LENGTH"]=500*1024*1024
ALLOWED={"mp4","mov","m4v","webm","mkv"}; JOBS={}; LOCK=threading.Lock()

def setjob(j,**kw):
    with LOCK:JOBS.setdefault(j,{}).update(kw)
def okfile(n): return "." in n and n.rsplit(".",1)[1].lower() in ALLOWED
def extract_url(s):
    m=re.search(r'https?://[^\s]+',str(s or ""))
    return m.group(0).rstrip('.,;，。！!）)】]') if m else ""
def is_douyin(u):
    try:
        h=(urlparse(u).hostname or "").lower()
        return h=="douyin.com" or h.endswith(".douyin.com")
    except:return False
def run(cmd,timeout=600):
    return subprocess.run(cmd,capture_output=True,text=True,timeout=timeout)
def clean_zh(s):
    s=re.sub(r"\s+","",s or "")
    return re.sub(r"[^\u3400-\u9fffA-Za-z0-9，。！？、：；,.!?…《》“”‘’\-]","",s).strip()
def similar(a,b):
    if a==b:return True
    if not a or not b:return False
    A,B=set(a),set(b)
    return len(A&B)/max(1,len(A|B))>=.76
def tr(text):
    for k in range(3):
        try:
            q=urllib.parse.quote(text)
            u="https://translate.googleapis.com/translate_a/single?client=gtx&sl=zh-CN&tl=vi&dt=t&q="+q
            req=urllib.request.Request(u,headers={"User-Agent":"Mozilla/5.0"})
            with urllib.request.urlopen(req,timeout=20) as r:d=json.loads(r.read().decode())
            v="".join(x[0] for x in d[0] if x and x[0]).strip()
            if v:return v
        except:time.sleep(k+1)
    return ""
def srt_time(x):
    ms=round(x*1000); h=ms//3600000; ms%=3600000; m=ms//60000; ms%=60000; s=ms//1000; ms%=1000
    return f"{h:02}:{m:02}:{s:02},{ms:03}"
def esc_filter(p): return str(p).replace("\\","/").replace(":","\\:").replace("'","\\'")
def download_worker(j,u):
    ident=uuid.uuid4().hex
    setjob(j,status="working",message="Đang lấy video Douyin…")
    p=run(["yt-dlp","--no-playlist","--socket-timeout","15","--retries","2","--merge-output-format","mp4",
           "-f","bv*+ba/b","-o",str(UPLOAD/(ident+".%(ext)s")),u],180)
    fs=list(UPLOAD.glob(ident+".*"))
    if p.returncode or not fs:
        setjob(j,status="error",message="Không lấy được link này. Hãy tải video lên trực tiếp.");return
    f=max(fs,key=lambda x:x.stat().st_size)
    setjob(j,status="done",message="Đã lấy video.",video_url="/media/uploads/"+f.name,stored_name=f.name)

def worker(j,name):
    video=UPLOAD/Path(name).name; cap=None
    try:
        setjob(j,status="working",stage=1,message="Đang OCR chữ Trung trên video…")
        cap=cv2.VideoCapture(str(video))
        if not cap.isOpened():raise RuntimeError("Không mở được video")
        fps=cap.get(cv2.CAP_PROP_FPS) or 25; total=int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        dur=total/fps if total else 0; sample=float(os.getenv("OCR_SAMPLE_SECONDS","0.65")); step=max(1,int(fps*sample))
        rows=[]; active=None; idx=0; n=0; expected=max(1,(total+step-1)//step)
        while not total or idx<total:
            cap.set(cv2.CAP_PROP_POS_FRAMES,idx); ok,frame=cap.read()
            if not ok:break
            h,w=frame.shape[:2]
            roi=frame[int(h*.55):int(h*.91),int(w*.03):int(w*.97)]
            gray=cv2.cvtColor(roi,cv2.COLOR_BGR2GRAY)
            gray=cv2.resize(gray,None,fx=1.5,fy=1.5,interpolation=cv2.INTER_LINEAR)
            # OCR both normal grayscale and threshold; keep the more plausible Chinese result.
            a=clean_zh(pytesseract.image_to_string(gray,lang="chi_sim",config="--psm 6"))
            _,bw=cv2.threshold(gray,175,255,cv2.THRESH_BINARY)
            b=clean_zh(pytesseract.image_to_string(bw,lang="chi_sim",config="--psm 6"))
            zh=max((a,b),key=lambda x:sum('\u3400'<=c<='\u9fff' for c in x))
            sec=idx/fps
            if len(zh)>=2 and any('\u3400'<=c<='\u9fff' for c in zh):
                if active and similar(active["zh"],zh):active["end"]=min(dur or sec+sample,sec+sample)
                else:
                    if active:rows.append(active)
                    active={"start":sec,"end":min(dur or sec+sample,sec+sample),"zh":zh}
            elif active and sec-active["end"]>sample*1.2:rows.append(active);active=None
            n+=1
            if n%3==0:setjob(j,message=f"Đang OCR chữ Trung… {min(n,expected)}/{expected}")
            idx+=step
        if active:rows.append(active)
        cap.release();cap=None
        if not rows:raise RuntimeError("Không đọc được chữ Trung ở vùng phụ đề phía dưới video.")
        setjob(j,status="working",stage=2,message=f"Đã đọc {len(rows)} đoạn. Đang dịch tiếng Việt…")
        out=[]
        for i,r in enumerate(rows):
            v=tr(r["zh"])
            if v:out.append({"start":r["start"],"end":max(r["end"],r["start"]+.7),"vi":v})
            setjob(j,message=f"Đang dịch… {i+1}/{len(rows)}")
        if not out:raise RuntimeError("Dịch FREE tạm thời không phản hồi.")
        srt=OUTPUT/(j+".srt")
        srt.write_text("\n\n".join(f"{i+1}\n{srt_time(r['start'])} --> {srt_time(r['end'])}\n{r['vi']}" for i,r in enumerate(out)),encoding="utf-8")
        outmp4=OUTPUT/(j+".mp4")
        setjob(j,status="working",stage=3,message="Đang ghép Vietsub vào MP4 bằng FFmpeg…")
        style="FontName=Noto Sans,FontSize=18,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=2,Shadow=1,Alignment=2,MarginV=28"
        vf=f"subtitles='{esc_filter(srt)}':force_style='{style}'"
        p=run(["ffmpeg","-y","-i",str(video),"-vf",vf,"-c:v","libx264","-preset","veryfast","-crf","23","-c:a","copy",str(outmp4)],900)
        if p.returncode:
            p=run(["ffmpeg","-y","-i",str(video),"-vf",vf,"-c:v","libx264","-preset","veryfast","-crf","23","-c:a","aac","-b:a","192k",str(outmp4)],900)
        if p.returncode or not outmp4.exists():raise RuntimeError("FFmpeg xuất video thất bại: "+(p.stderr or "")[-500:])
        setjob(j,status="done",stage=4,message="Hoàn tất Vietsub.",count=len(out),video_url="/media/outputs/"+outmp4.name,srt_url="/media/outputs/"+srt.name)
    except Exception as e:
        if cap is not None:cap.release()
        setjob(j,status="error",message="Lỗi: "+str(e))

@app.get("/")
def home():return render_template("index.html")
@app.get("/api/health")
def health():
    def ver(x):
        try:return run([x,"--version"],20).stdout.splitlines()[0]
        except:return "missing"
    return jsonify(ok=True,tesseract=ver("tesseract"),ffmpeg=ver("ffmpeg"))
@app.post("/api/upload")
def upload():
    f=request.files.get("video")
    if not f or not f.filename:return jsonify(ok=False,error="Chưa chọn video"),400
    if not okfile(f.filename):return jsonify(ok=False,error="Định dạng video chưa hỗ trợ"),400
    ext=f.filename.rsplit(".",1)[1].lower(); name=uuid.uuid4().hex+"."+ext; f.save(UPLOAD/name)
    return jsonify(ok=True,stored_name=name,video_url="/media/uploads/"+name,filename=secure_filename(f.filename))
@app.post("/api/douyin/start")
def ds():
    u=extract_url((request.get_json(silent=True) or {}).get("url"))
    if not u or not is_douyin(u):return jsonify(ok=False,error="Link Douyin không hợp lệ"),400
    j=uuid.uuid4().hex[:12];setjob(j,status="queued",message="Đã nhận link")
    threading.Thread(target=download_worker,args=(j,u),daemon=True).start()
    return jsonify(ok=True,job_id=j)
@app.get("/api/douyin/status/<j>")
def dst(j):
    with LOCK:d=JOBS.get(j)
    return (jsonify(ok=True,**d) if d else (jsonify(ok=False,error="Job không tồn tại"),404))
@app.post("/api/vietsub/start")
def vs():
    name=Path(str((request.get_json(silent=True) or {}).get("stored_name",""))).name
    if not name or not (UPLOAD/name).exists():return jsonify(ok=False,error="Không tìm thấy video"),400
    j=uuid.uuid4().hex[:12];setjob(j,status="queued",stage=0,message="Chuẩn bị OCR…")
    threading.Thread(target=worker,args=(j,name),daemon=True).start()
    return jsonify(ok=True,job_id=j)
@app.get("/api/vietsub/status/<j>")
def vst(j):
    with LOCK:d=JOBS.get(j)
    return (jsonify(ok=True,**d) if d else (jsonify(ok=False,error="Job không tồn tại"),404))
@app.get("/media/uploads/<path:n>")
def mu(n):return send_from_directory(UPLOAD,n,conditional=True)
@app.get("/media/outputs/<path:n>")
def mo(n):return send_from_directory(OUTPUT,n,conditional=True,as_attachment=False)
if __name__=="__main__":app.run(host="0.0.0.0",port=int(os.getenv("PORT","10000")))
