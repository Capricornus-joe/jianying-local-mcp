"""Validated editing controls and resource-independent linear motion presets."""
from __future__ import annotations
from copy import deepcopy
import math
import re

ADVANCED_FIELDS = {'transform', 'crop', 'text_style', 'keyframes', 'audio_fade', 'mask', 'animations', 'transition_out'}
TRANSFORM_RANGES = {'x':(-4,4), 'y':(-4,4), 'scale_x':(.01,20),
                    'scale_y':(.01,20), 'rotation':(-3600,3600), 'opacity':(0,1)}
TEXT_RANGES = {'stroke_width':(0,100), 'background_opacity':(0,1),
               'background_radius':(0,1), 'shadow_opacity':(0,1),
               'shadow_diffuse':(0,100), 'shadow_distance':(0,100),
               'shadow_angle':(-360,360), 'letter_spacing':(-10,100),
               'line_spacing':(-1,10)}

def finite(value, low, high, label):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'{label} must be a finite number between {low} and {high}')
    return float(value)

def _object(value, keys, label):
    if not isinstance(value,dict) or set(value)-set(keys):
        raise ValueError(f'{label}: unknown fields; allowed: {sorted(keys)}')
    return value

def normalize_advanced(raw:dict, kind:str, duration:float)->dict:
    result = {}
    if 'transform' in raw:
        if kind=='audio':
            raise ValueError('Audio does not support visual transforms')
        allowed=set(TRANSFORM_RANGES)|{'flip_horizontal','flip_vertical'}
        value=_object(raw['transform'],allowed,'transform')
        out={}
        for key,v in value.items():
            if key.startswith('flip_'):
                if not isinstance(v,bool): raise ValueError(f'{key} must be boolean')
                out[key]=v
            else: out[key]=finite(v,*TRANSFORM_RANGES[key],key)
        result['transform']=out
    if 'crop' in raw:
        if kind not in {'video','image'}: raise ValueError('Crop needs a video or image')
        value=_object(raw['crop'],{'left','top','right','bottom'},'crop')
        if set(value)!={'left','top','right','bottom'}: raise ValueError('Crop requires four normalized bounds')
        value={k:finite(v,0,1,k) for k,v in value.items()}
        if value['left']>=value['right'] or value['top']>=value['bottom']:
            raise ValueError('Crop must have positive width and height')
        result['crop']=value
    if 'text_style' in raw:
        if kind!='text': raise ValueError('text_style needs a text clip')
        colors={'stroke_color','background_color','shadow_color'}
        booleans={'bold','italic','underline'}
        value=_object(raw['text_style'],set(TEXT_RANGES)|colors|booleans|{'alignment'},'text_style')
        out={}
        for key,v in value.items():
            if key in TEXT_RANGES: out[key]=finite(v,*TEXT_RANGES[key],key)
            elif key in colors:
                if not isinstance(v,str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',v): raise ValueError(f'{key} must be #RRGGBB')
                out[key]=v.upper()
            elif key in booleans:
                if not isinstance(v,bool): raise ValueError(f'{key} must be boolean')
                out[key]=v
            else:
                if v not in {'left','center','right'}: raise ValueError('alignment must be left, center or right')
                out[key]=v
        result['text_style']=out
    if 'keyframes' in raw:
        if kind=='audio': raise ValueError('Audio volume keyframes are not yet validated; use audio_fade')
        value=_object(raw['keyframes'],TRANSFORM_RANGES,'keyframes')
        out={}
        for prop,points in value.items():
            if not isinstance(points,list) or not 1<=len(points)<=1000:
                raise ValueError('Each keyframe property requires 1–1000 points')
            normalized=[]; times=set()
            for point in points:
                _object(point,{'time','value'},'keyframe point')
                if set(point)!={'time','value'}: raise ValueError('Each point needs time and value')
                time=round(finite(point['time'],0,duration,'keyframe time')*1_000_000)/1_000_000
                if time in times: raise ValueError('Keyframe times must be unique at microsecond precision')
                times.add(time)
                normalized.append({'time':time,'value':finite(point['value'],*TRANSFORM_RANGES[prop],prop)})
            out[prop]=sorted(normalized,key=lambda p:p['time'])
        result['keyframes']=out
    if 'audio_fade' in raw:
        if kind not in {'video','audio'}: raise ValueError('Audio fades need an audio/video clip')
        value=_object(raw['audio_fade'],{'in','out'},'audio_fade')
        out={key:finite(value.get(key,0),0,duration,'audio fade '+key) for key in ('in','out')}
        if out['in']+out['out']>duration+1e-6: raise ValueError('Audio fades cannot overlap')
        result['audio_fade']=out
    if 'mask' in raw:
        if kind not in {'video','image'}: raise ValueError('Mask requires video or image')
        keys={'shape','x','y','width','height','rotation','feather','invert','round_corner'}
        value=_object(raw['mask'],keys,'mask'); out={}
        if value.get('shape') not in {'circle','rectangle','linear'}: raise ValueError('Mask shape must be circle, rectangle or linear')
        out['shape']=value['shape']
        bounds={'x':(-1,1),'y':(-1,1),'width':(.001,2),'height':(.001,2),
                'rotation':(-360,360),'feather':(0,100),'round_corner':(0,100)}
        for key in bounds:
            if key in value: out[key]=finite(value[key],*bounds[key],'mask.'+key)
        if 'invert' in value:
            if not isinstance(value['invert'],bool): raise ValueError('mask.invert must be boolean')
            out['invert']=value['invert']
        result['mask']=out
    if 'animations' in raw:
        if kind=='audio': raise ValueError('Native animations need a visual clip')
        values=raw['animations']
        if not isinstance(values,list) or not 1<=len(values)<=3: raise ValueError('animations must contain one to three phases')
        phases=set(); out=[]
        for value in values:
            _object(value,{'type','duration','resource'},'animation')
            phase=value.get('type')
            if phase not in {'in','out','group'} or phase in phases: raise ValueError('Each animation phase must be in/out/group and unique')
            phases.add(phase)
            out.append({'type':phase,'duration':finite(value.get('duration'),.001,duration,'animation.duration'),
                        'resource':normalize_resource(value.get('resource'))})
        if 'group' in phases and len(phases)>1: raise ValueError('Group animation cannot combine with entrance/exit animations')
        if sum(item['duration'] for item in out)>duration+1e-6: raise ValueError('Animation intervals cannot overlap')
        result['animations']=out
    if 'transition_out' in raw:
        if kind not in {'video','image'}: raise ValueError('Transition needs a video/image clip')
        value=_object(raw['transition_out'],{'duration','resource'},'transition_out')
        result['transition_out']={'duration':finite(value.get('duration'),.001,duration,'transition duration'),
                                  'resource':normalize_resource(value.get('resource'))}
    return result

def normalize_resource(value):
    from pathlib import Path
    keys={'name','effect_id','resource_id','path','category_id','category_name','is_overlap'}
    value=_object(value,keys,'resource'); out={}
    for key in ('name','effect_id','resource_id'):
        item=value.get(key)
        if not isinstance(item,str) or not item or len(item)>200 or any(ord(c)<32 for c in item):
            raise ValueError('Resource needs nonempty string name, effect_id and resource_id')
        out[key]=item
    if not out['effect_id'].isdigit() or not out['resource_id'].isdigit(): raise ValueError('Native resource IDs must be digit strings')
    for key in ('category_id','category_name'):
        if key in value:
            if not isinstance(value[key],str) or len(value[key])>200: raise ValueError('Invalid resource category')
            out[key]=value[key]
    if 'path' in value:
        path=value['path']
        if not isinstance(path,str) or not Path(path).is_absolute() or not Path(path).is_dir():
            raise ValueError('Resource path must be an existing absolute local directory')
        out['path']=str(Path(path).resolve())
    if 'is_overlap' in value:
        if not isinstance(value['is_overlap'],bool): raise ValueError('resource.is_overlap must be boolean')
        out['is_overlap']=value['is_overlap']
    return out

MOTION_PRESETS = {
    'zoom_in': '缓慢推近', 'zoom_out': '缓慢拉远', 'pan_left':'从右向左平移',
    'pan_right':'从左向右平移', 'slide_up':'从下方滑入', 'slide_down':'从上方滑入',
    'fade_in':'透明度渐显', 'fade_out':'透明度渐隐', 'pulse':'放大后恢复',
}

def motion_keyframes(preset:str,duration:float,strength:float=.15)->dict:
    duration=finite(duration,.001,86400,'duration')
    strength=finite(strength,.01,1,'strength')
    if preset not in MOTION_PRESETS: raise ValueError(f'Unknown preset; choose {sorted(MOTION_PRESETS)}')
    def points(*values): return [{'time':round(i*duration/(len(values)-1),6),'value':v} for i,v in enumerate(values)]
    if preset=='zoom_in': return {p:points(1,1+strength) for p in ('scale_x','scale_y')}
    if preset=='zoom_out': return {p:points(1+strength,1) for p in ('scale_x','scale_y')}
    if preset=='pan_left': return {'x':points(strength,-strength)}
    if preset=='pan_right': return {'x':points(-strength,strength)}
    if preset=='slide_up': return {'y':points(-strength,0),'opacity':points(0,1)}
    if preset=='slide_down': return {'y':points(strength,0),'opacity':points(0,1)}
    if preset=='fade_in': return {'opacity':points(0,1)}
    if preset=='fade_out': return {'opacity':points(1,0)}
    return {p:points(1,1+strength,1) for p in ('scale_x','scale_y')}

def sliced_keyframes(keyframes:dict,start:float,end:float)->dict:
    """Preserve a linear animation exactly over a trimmed subinterval."""
    def sample(points,time):
        if time<=points[0]['time']: return points[0]['value']
        for a,b in zip(points,points[1:]):
            if time<=b['time']:
                t=(time-a['time'])/(b['time']-a['time'])
                return a['value']+(b['value']-a['value'])*t
        return points[-1]['value']
    out={}
    for prop,points in keyframes.items():
        kept=[{'time':round(p['time']-start,6),'value':p['value']} for p in points if start<p['time']<end]
        out[prop]=[{'time':0.0,'value':sample(points,start)},*kept,{'time':round(end-start,6),'value':sample(points,end)}]
    return out

def update_clip_features(store,name,new_name,clip_ids,features,dry_run=True):
    if not isinstance(clip_ids,list) or not clip_ids or len(set(clip_ids))!=len(clip_ids):
        raise ValueError('clip_ids must be a nonempty unique list')
    if not isinstance(features,dict) or not features or set(features)-ADVANCED_FIELDS:
        raise ValueError(f'Allowed feature groups: {sorted(ADVANCED_FIELDS)}')
    plan=deepcopy(store.load_managed(name)); plan['name']=new_name
    existing={c['id'] for c in plan['clips']}
    if set(clip_ids)-existing: raise ValueError('Unknown clip IDs')
    for clip in plan['clips']:
        if clip['id'] in clip_ids:
            for group,value in features.items():
                if value is None:
                    clip.pop(group,None)
                elif group in {'transform','text_style','keyframes'}:
                    if not isinstance(value,dict): raise ValueError(f'{group} must be an object')
                    clip[group]={**clip.get(group,{}),**deepcopy(value)}
                else: clip[group]=deepcopy(value)
    return store.create(plan,dry_run=dry_run)

def apply_motion(store,name,new_name,clip_ids,preset,strength=.15,dry_run=True):
    plan=deepcopy(store.load_managed(name)); plan['name']=new_name
    if not isinstance(clip_ids,list) or not clip_ids or len(set(clip_ids))!=len(clip_ids):
        raise ValueError('clip_ids must be a nonempty unique list')
    if set(clip_ids)-{c['id'] for c in plan['clips']}: raise ValueError('Unknown clip IDs')
    for clip in plan['clips']:
        if clip['id'] in clip_ids:
            if clip['kind']=='audio': raise ValueError('Motion presets require visual clips')
            clip['keyframes']={**clip.get('keyframes',{}),**motion_keyframes(preset,clip['duration'],strength)}
    return store.create(plan,dry_run=dry_run)
