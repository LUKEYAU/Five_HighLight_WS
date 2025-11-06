import argparse
import time
from pathlib import Path

import cv2
import torch
import torch.backends.cudnn as cudnn
from numpy import random

from models.experimental import attempt_load
from utils.datasets import LoadStreams, LoadImages
from utils.general import check_img_size, check_requirements, check_imshow, non_max_suppression, apply_classifier, \
    scale_coords, xyxy2xywh, strip_optimizer, set_logging, increment_path
from utils.plots import plot_one_box
from utils.torch_utils import select_device, load_classifier, time_synchronized, TracedModel

from tqdm import tqdm
import json

def detect(save_img=False):
    source, weights, save_txt, imgsz, trace = opt.source, opt.weights, opt.save_txt, opt.img_size, not opt.no_trace
    save_img = not opt.nosave and not source.endswith('.txt')  # save inference images
    webcam = source.isnumeric() or source.endswith('.txt') or source.lower().startswith(
        ('rtsp://', 'rtmp://', 'http://', 'https://'))
    
    input_video = source.endswith('.mp4') or source.endswith('.avi') or source.endswith('.mkv')
    
    #!check the video
    cap = cv2.VideoCapture(source)

    if not cap.isOpened():
        print("Cannot open the video")
    else:
        print("----影片可以成功讀取-------")
   
    
    
    # Directories
    save_dir = Path(increment_path(Path(opt.project) / opt.name, exist_ok=opt.exist_ok))  # increment run
    (save_dir / 'labels' if save_txt else save_dir).mkdir(parents=True, exist_ok=True)  # make dir

    (save_dir / 'image' if save_txt else save_dir).mkdir(parents=True, exist_ok=True)

    device = select_device(opt.device)
    half = device.type != 'cpu'  # half 
    # precision only supported on CUDA
    
    # Load model
    model = attempt_load(weights, map_location=device)  # load FP32 model
    #checking the model
    #print(f'checking the model{model}')
    
    #check the map location
    #print(f'the map location is:{device}')
    
    
    stride = int(model.stride.max())  # model stride
    imgsz = check_img_size(imgsz, s=stride)  # check img_size
    
    if half:                      #把模型的精度降為一半 float32 -> float16 更快 省mem
        model.half()  # to FP16
    
    # Set Dataloader
    vid_path, vid_writer = None, None
    if webcam:
        cudnn.benchmark = True  # set True to speed up constant image size inference
        dataset = LoadStreams(source, img_size=imgsz, stride=stride)
    else:
        #check if the load works
        dataset = LoadImages(source, img_size=imgsz, stride=stride)
    
    
    # Get names and colors
    names = model.module.names if hasattr(model, 'module') else model.names  #取得所有label的名稱
    colors = [[random.randint(0, 255) for _ in range(3)] for _ in names]     #label框對應的顏色
 
    if opt.write_log:
        with open('%s.txt' % opt.write_log, 'a') as f:
            f.write('Frame Person Ball Ball_Pos\n')
            
    results = {}
    
    
    if input_video:
        for _, _, _, vid_cap in dataset:
            vid_len = int(vid_cap.get(cv2.CAP_PROP_FRAME_COUNT))
            pbar = tqdm(total=int(vid_len))
            break
    
    for idx, (path, img, im0s, vid_cap) in enumerate(dataset):   #im0s為原圖, img為近模型的size
        print(f'processing frame {idx}.....')
        #im0 = cv2.resize(im0s, (854, 480))
        img = torch.from_numpy(img).to(device)
        img = img.half() if half else img.float()  # uint8 to fp16/32
        img /= 255.0  # 0 - 255 to 0.0 - 1.0
        if img.ndimension() == 3:
            img = img.unsqueeze(0)  #進模型前多一個維度 batch_size
               
       
        # Inference
        t1 = time_synchronized()
        pred = model(img, augment=opt.augment)[0]
        #check the pred
        #print(f'check pred value:{pred}')
        
        
        t2 = time_synchronized()
        # Apply NMS
        pred = non_max_suppression(pred, opt.conf_thres, opt.iou_thres, classes=opt.classes, agnostic=opt.agnostic_nms)
        #!check
        #print(f'the pred after non_max_surpression : {pred}')
        t3 = time_synchronized()

        #print(f'{opt.classes=}, {opt.augment=}')

        # Process detections
        person_count = 0
        ball_count = 0
        ball_pos = []
        
        #print(f'{pred=}')

        save_result = {}
        for i, det in enumerate(pred):  # detections per image
            if webcam:  # batch_size >= 1
                p, s, im0, frame = path[i], '%g: ' % i, im0s[i].copy(), dataset.count
            else:
                p, s, im0, frame = path, '', im0s, getattr(dataset, 'frame', 0)

            p = Path(p)  # to Path
            save_path = str(save_dir / p.name)  # img.jpg
            txt_path = str(save_dir / 'labels' / p.stem) + ('' if dataset.mode == 'image' else f'_{frame}')  # img.txt

            img_path = str(save_dir / 'image' / p.stem) + ('' if dataset.mode == 'image' else f'_{frame}')
            
            gn = torch.tensor(im0.shape)[[1, 0, 1, 0]]  # normalization gain whwh
            if len(det):
                # Rescale boxes from img_size to im0 size
                det[:, :4] = scale_coords(img.shape[2:], det[:, :4], im0.shape).round()
                # print("check1")
                #print(f'{det=}')
                # exit()

                # Print results
                # for c in det[:, -1].unique():
                #     n = (det[:, -1] == c).sum()  # detections per class
                #     s += f"{n} {names[int(c)]}{'s' * (n > 1)}, "  # add to string
                    
                
                # Write results
                for *xyxy, conf, cls in reversed(det):
                    if save_txt:  # Write to file
                        xywh = (xyxy2xywh(torch.tensor(xyxy).view(1, 4)) / gn).view(-1).tolist()  # normalized xywh
                        line = (cls, *xywh, conf) if opt.save_conf else (cls, *xywh)  # label format
                        #print(f'{gn=}{xywh=}, {line=}, {cls=}')
                        # print("check")
                        # cv2.imwrite('./testframe.jpg', im0)
                        # exit()
                        if(cls == 1):# write ball label
                            # ball_pos.append(('%g ' * len(line)).rstrip() % line)
                            ball_pos.append([[int(xyxy[0]), int(xyxy[1])], [int(xyxy[2]), int(xyxy[3])], conf.item()])
                        name = names[int(cls)]
                        if not name in save_result:
                            save_result[name] = []

                        save_result[name].append([[int(xyxy[0]), int(xyxy[1])], [int(xyxy[2]), int(xyxy[3])], conf.item()])
                        
                        
                        with open(txt_path + '.txt', 'a') as f:
                            f.write(('%g ' * len(line)).rstrip() % line + '\n')
                            # cv2.imwrite(img_path + '.jpg', im0)

                    if save_img:  # Add bbox to image
                        label = f'{names[int(cls)]} {conf:.2f}'
                        plot_one_box(xyxy, im0, label=label, color=colors[int(cls)], line_thickness=2)
                        if('person' in label):
                            person_count += 1
                        elif('ball' in label):
                            ball_count += 1 
                        # if(int(cls) == 1):
                        #     plot_one_box(xyxy, im0, label=label, color=(255, 0, 0), line_thickness=1)
                        #####################################################
                        # if('person' in label):
                        #     continue
                        # else:
                        #     plot_one_box(xyxy, im0, label=label, color=colors[int(cls)], line_thickness=1)
                        #####################################################
                        
            results[str(idx)] = save_result
            
            # print(f'{s}Done. ({(1E3 * (t2 - t1)):.1f}ms) Inference, ({(1E3 * (t3 - t2)):.1f}ms) NMS')
            
            # Save results (image with detections)
            if save_img:
                if dataset.mode == 'image':
                    cv2.imwrite(save_path, im0)
                    #print(f" The image with the result is saved in: {save_path}")
                else:  # 'video' or 'stream'
                    if vid_path != save_path:  # new video
                        vid_path = save_path
                        if isinstance(vid_writer, cv2.VideoWriter):
                            vid_writer.release()  # release previous video writer
                        if vid_cap:  # video
                            fps = vid_cap.get(cv2.CAP_PROP_FPS)
                            w = int(vid_cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                            h = int(vid_cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                        else:  # stream
                            fps, w, h = 30, im0.shape[1], im0.shape[0]
                            save_path += '.mp4'
                        vid_writer = cv2.VideoWriter(save_path, cv2.VideoWriter_fourcc(*'mp4v'), fps, (w, h))
                        #vid_writer = cv2.VideoWriter(save_path, cv2.VideoWriter_fourcc(*'mp4v'),  fps, (854, 480))
                    

                    vid_writer.write(im0)
                    
            if opt.write_log:
                with open('%s.txt' % opt.write_log, 'a') as f:
                    f.write('%d %d %d %s\n' % (int(frame), person_count, ball_count, str(ball_pos)))

        if input_video:
            pbar.update(1)
            
    if input_video:
        pbar.close()
        
    if opt.save_json:
        with open(save_path[:-3] + 'json', "w") as outfile:
            json.dump(results, outfile)
            
#     if save_txt or save_img:
#         s = f"\n{len(list(save_dir.glob('labels/*.txt')))} labels saved to {save_dir / 'labels'}" if save_txt else ''
#         print(f"Results saved to {save_dir}{s}")
    
    # print(f'Done. ({time.time() - t0:.3f}s)')
    

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--weights', nargs='+', type=str, default='yolov7.pt', help='model.pt path(s)')
    parser.add_argument('--source', type=str, default='inference/images', help='source')  # file/folder, 0 for webcam
    parser.add_argument('--img-size', type=int, default=640, help='inference size (pixels)')
    parser.add_argument('--conf-thres', type=float, default=0.05, help='object confidence threshold')
    parser.add_argument('--iou-thres', type=float, default=0.45, help='IOU threshold for NMS')
    parser.add_argument('--device', default='', help='cuda device: 0 or 0,1,2,3 or cpu; empty = auto')
    parser.add_argument('--save-txt', action='store_true', help='save results to *.txt')
    parser.add_argument('--save-conf', action='store_true', help='save confidences in --save-txt labels')
    parser.add_argument('--nosave', action='store_true', help='do not save images/videos')
    parser.add_argument('--classes', nargs='+', type=int, help='filter by class: --class 0, or --class 0 2 3')
    parser.add_argument('--agnostic-nms', action='store_true', help='class-agnostic NMS')
    parser.add_argument('--augment', action='store_true', help='augmented inference')
    parser.add_argument('--update', action='store_true', help='update all models')
    parser.add_argument('--project', default='runs/detect', help='save results to project/name')
    parser.add_argument('--name', default='exp', help='save results to project/name')
    parser.add_argument('--exist-ok', action='store_true', help='existing project/name ok, do not increment')
    parser.add_argument('--no-trace', action='store_true', help='don`t trace model')
    
    parser.add_argument('--write-log', default='')
    parser.add_argument('--save-json', action='store_true')
    opt = parser.parse_args()
    # print(opt)
    #check_requirements(exclude=('pycocotools', 'thop'))

    with torch.no_grad():
        if opt.update:  # update all models (to fix SourceChangeWarning)
            for opt.weights in ['yolov7.pt']:
                detect()
                strip_optimizer(opt.weights)
        else:
            detect()
