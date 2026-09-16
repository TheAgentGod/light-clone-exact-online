from PIL import Image
import numpy as np, cv2, joblib, sys, os, json

HERE=os.path.dirname(os.path.abspath(__file__))
model=joblib.load(os.path.join(HERE,"light_clone_v1.joblib"))
gray_res=np.load(os.path.join(HERE,"gray_residual.npy"))
with open(os.path.join(HERE,"jpeg_qtables.json"),"r",encoding="utf-8") as f:
    Q={int(k):v for k,v in json.load(f).items()}

def load_rgb(path):
    return np.array(Image.open(path).convert("RGB")).astype(np.float32)/255.0

def make_features(img):
    h,w,_=img.shape
    fs=[np.ones((h,w,1),np.float32), img]
    for sigma in [0.8,2.0,6.0,18.0]:
        b=np.stack([cv2.GaussianBlur(img[:,:,c],(0,0),sigmaX=sigma,sigmaY=sigma) for c in range(3)],axis=2)
        fs += [b, img-b]
    lum=(0.2126*img[:,:,0]+0.7152*img[:,:,1]+0.0722*img[:,:,2]).astype(np.float32)
    gx=cv2.Sobel(lum,cv2.CV_32F,1,0,ksize=3)
    gy=cv2.Sobel(lum,cv2.CV_32F,0,1,ksize=3)
    gm=np.sqrt(gx*gx+gy*gy)
    fs += [lum[:,:,None], gm[:,:,None]]
    gr=cv2.resize(gray_res,(w,h),interpolation=cv2.INTER_CUBIC)
    fs += [gr]
    yy,xx=np.mgrid[0:h,0:w].astype(np.float32)
    xn=(xx/(w-1)-.5); yn=(yy/(h-1)-.5)
    fs += [np.stack([xn,yn,xn*xn,yn*yn,xn*yn],axis=2)]
    return np.concatenate(fs,axis=2)

inp=sys.argv[1]
out=sys.argv[2]
img=load_rgb(inp)
F=make_features(img).reshape(-1,38)
pred=np.empty((F.shape[0],3),np.float32)
for s in range(0,F.shape[0],200000):
    pred[s:s+200000]=model.predict(F[s:s+200000])
pred=np.clip(pred,0,1).reshape(img.shape)

# IMPORTANT: do not re-encode this output later with Sharp, Canvas, browser APIs, etc.
# These qtables are part of the validated pipeline.
Image.fromarray((pred*255+0.5).astype(np.uint8),"RGB").save(
    out,"JPEG",qtables=Q,subsampling=2,optimize=False
)
print(out)
