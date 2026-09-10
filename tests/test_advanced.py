import json
from copy import deepcopy
import pytest
from jianying_local_mcp.advanced import normalize_advanced, motion_keyframes, sliced_keyframes, update_clip_features
from jianying_local_mcp.core import ProjectStore, normalize_plan
from jianying_local_mcp.native import build_native

@pytest.mark.parametrize('group,value,kind',[
 ('transform',{'scale_x':0},'video'),('transform',{'opacity':2},'text'),
 ('transform',{'flip_vertical':1},'video'),('crop',{'left':.5,'top':0,'right':.4,'bottom':1},'video'),
 ('text_style',{'bold':'true'},'text'),('text_style',{'stroke_color':'red'},'text'),
 ('keyframes',{'x':[{'time':1,'value':0},{'time':1,'value':1}]},'video'),
 ('keyframes',{'opacity':[{'time':1,'value':1}]},'audio'),
 ('audio_fade',{'in':2,'out':2},'audio'),('mask',{'shape':'square'},'video')])
def test_invalid_advanced_controls(group,value,kind):
 with pytest.raises(ValueError): normalize_advanced({group:value},kind,3)

def test_linear_trim_preserves_boundary_values():
 keys={'x':[{'time':0,'value':-1},{'time':2,'value':1},{'time':4,'value':0}]}
 assert sliced_keyframes(keys,1,3)['x']==[{'time':0,'value':0},{'time':1,'value':1},{'time':2,'value':.5}]
 assert keys['x'][0]['value']==-1

def test_motion_preset_can_write_and_split_without_losing_animation(tmp_path):
 store=ProjectStore(tmp_path)
 plan={'name':'animated','clips':[{'id':'t','kind':'text','text':'测试😀字幕','start':0,'duration':4,
 'keyframes':motion_keyframes('pan_right',4,.4),'text_style':{'bold':True,'stroke_color':'#000000','stroke_width':20}}]}
 result=store.create(plan,False)
 before=(tmp_path/'animated'/'draft_info.json').read_bytes()
 split=store.edit('animated','split',[{'op':'split','id':'t','at':2}],False)
 clips=store.load_managed('split')['clips']
 assert clips[0]['keyframes']['x'][-1]['value']==pytest.approx(0)
 assert clips[1]['keyframes']['x'][0]['value']==pytest.approx(0)
 assert clips[1]['keyframes']['x'][-1]['value']==pytest.approx(.4)
 assert before==(tmp_path/'animated'/'draft_info.json').read_bytes()
 assert split['summary']['duration']==4

def test_crop_does_not_mutate_other_use_of_same_media(tmp_path):
 def probe(path): return {'path':path,'kind':'video','duration':4,'width':1280,'height':720,'has_audio':False}
 clips=[{'id':'a','kind':'video','track':'main','path':'/synthetic.mp4','start':0,'duration':2},
        {'id':'b','kind':'video','track':'main','path':'/synthetic.mp4','start':2,'duration':2,'crop':{'left':.2,'right':.8,'top':0,'bottom':1}}]
 plan=normalize_plan({'name':'crop','clips':clips},probe)
 info=build_native(plan,tmp_path/'crop')['draft_info.json']
 mats={m['id']:m for m in info['materials']['videos']}
 segments=info['tracks'][0]['segments']
 assert len(mats)==2
 assert mats[segments[0]['material_id']]['crop']['upper_left_x']==0
 assert mats[segments[1]['material_id']]['crop']['upper_left_x']==.2

def test_group_merging_preserves_existing_controls(tmp_path):
 store=ProjectStore(tmp_path)
 store.create({'name':'base','clips':[{'id':'t','kind':'text','text':'a','start':0,'duration':2,'transform':{'scale_x':.5}}]},False)
 result=update_clip_features(store,'base','next',['t'],{'transform':{'rotation':15}},True)
 assert result['plan']['clips'][0]['transform']=={'scale_x':.5,'rotation':15}
 assert not (tmp_path/'next').exists()

def test_transition_requires_adjacent_following_clip(tmp_path):
 probe=lambda p:{'path':p,'kind':'video','duration':4,'width':1280,'height':720,'has_audio':False}
 clip={'id':'a','kind':'video','path':'/a.mp4','duration':2,'transition_out':{'duration':.5,'resource':{'name':'叠化','effect_id':'322577','resource_id':'6724845717472416269'}}}
 with pytest.raises(ValueError,match='following'): normalize_plan({'name':'bad','clips':[clip]},probe)
 second={**clip,'id':'b','start':3};second.pop('transition_out')
 with pytest.raises(ValueError,match='adjacent'): normalize_plan({'name':'bad','clips':[clip,second]},probe)
