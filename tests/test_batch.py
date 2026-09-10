from copy import deepcopy
import json
from unittest.mock import patch
import pytest
from jianying_local_mcp.batch import batch_edit
from jianying_local_mcp.core import ProjectStore
from jianying_local_mcp.advanced import update_clip_features, apply_motion
from jianying_local_mcp import workflow


@pytest.fixture
def store(tmp_path):
    s = ProjectStore(tmp_path/'projects')
    s.create({'name':'source', 'clips':[
        {'id':'a','kind':'text','text':'甲','track':'字幕','start':0,'duration':2},
        {'id':'b','kind':'text','text':'乙','track':'字幕','start':2,'duration':2},
    ]}, dry_run=False)
    return s


def steps():
    return [
        {'action':'edit','operations':[{'op':'update','id':'a','changes':{'text':'新字幕'}}]},
        {'action':'features','clip_ids':['a'],'features':{'text_style':{'bold':True}}},
        {'action':'features','clip_ids':['a'],'features':{'text_style':{'stroke_color':'#000000','stroke_width':2}}},
        {'action':'style_subtitles','style':{'font_size':42},'track':'字幕'},
        {'action':'motion','clip_ids':['a'],'preset':'fade_in','strength':.2},
    ]


def test_one_commit_matches_sequential_helpers(store):
    source_before = (store.workspace/'source/jianying_mcp_project.json').read_bytes()
    with patch.object(store, 'create', wraps=store.create) as create:
        result = batch_edit(store, 'source', 'batched', steps(), dry_run=False)
        assert create.call_count == 1
    assert result['committed_revisions'] == 1 and result['batch_steps'] == 5
    assert result['review_scope']['changed_clip_ids'] == ['a','b']
    assert result['review_scope']['audio_review_required'] is False
    store.edit('source','s1',steps()[0]['operations'],False)
    update_clip_features(store,'s1','s2',['a'],steps()[1]['features'],False)
    update_clip_features(store,'s2','s3',['a'],steps()[2]['features'],False)
    workflow.style_subtitles(store,'s3','s4',{'font_size':42},track='字幕',dry_run=False)
    sequential = apply_motion(store,'s4','s5',['a'],'fade_in',.2,False)
    assert result['plan']['clips'] == sequential['plan']['clips']
    assert (store.workspace/'source/jianying_mcp_project.json').read_bytes() == source_before
    assert not list(store.workspace.glob('batch-stage*'))
    assert json.loads((store.workspace/'batched/draft_info.json').read_text())['tracks']


def test_failed_late_step_has_no_partial_writes(store):
    before = {str(p.relative_to(store.workspace)):p.read_bytes() for p in store.workspace.rglob('*') if p.is_file()}
    bad = steps()+[{'action':'features','clip_ids':['missing'],'features':{'transform':{'x':.2}}}]
    with pytest.raises(ValueError,match='Batch step 6'):
        batch_edit(store,'source','failed',bad,False)
    after = {str(p.relative_to(store.workspace)):p.read_bytes() for p in store.workspace.rglob('*') if p.is_file()}
    assert after == before


def test_dry_run_validates_but_does_not_write(store):
    result=batch_edit(store,'source','preview',steps())
    assert result['status']=='validated' and result['committed_revisions']==0
    assert not (store.workspace/'preview').exists()


def test_srt_import_then_style_and_reorder(store):
    result=batch_edit(store,'source','new',[
        {'action':'subtitles','content':'1\n00:00:04,000 --> 00:00:05,000\n丙\n','track':'旁白'},
        {'action':'style_subtitles','style':{'color':'#00FF00'},'track':'旁白'},
        {'action':'reorder','track':'字幕','clip_ids':['b','a']},
    ])
    clips=result['plan']['clips']
    assert [(c['id'],c['start']) for c in clips if c['track']=='字幕']==[('b',0),('a',2)]
    assert next(c for c in clips if c['track']=='旁白')['color']=='#00FF00'


def test_animated_ripple_retains_guard(store):
    with pytest.raises(ValueError,match='keyframes|animations'):
        batch_edit(store,'source','bad',steps()+[{'action':'ripple_delete','start':.5,'end':1}])


@pytest.mark.parametrize('invalid',[[],[{'action':'publish'}],[{'action':'edit','operations':[],'unknown':True}],['bad']])
def test_invalid_steps(store,invalid):
    with pytest.raises(ValueError):batch_edit(store,'source','bad',invalid,False)
    assert not (store.workspace/'bad').exists()


def test_existing_destination_is_not_overwritten(store):
    with pytest.raises(ValueError):batch_edit(store,'source','source',steps(),False)


def test_identical_clip_remove_append_changes_visual_track_order(tmp_path):
    s=ProjectStore(tmp_path/'projects')
    clips=[{'id':x,'kind':'text','text':x,'track':x,'start':0,'duration':5} for x in ['lower','upper']]
    s.create({'name':'layers','clips':clips},False)
    result=batch_edit(s,'layers','reordered',[{'action':'edit','operations':[
        {'op':'remove','id':'lower'},{'op':'append','clip':clips[0]}]}])
    scope=result['review_scope']
    assert scope['visual_layer_order_changed'] is True
    assert scope['changed_clip_ids']==['lower','upper']
    assert scope['affected_ranges_seconds']==[[0,5]]


def test_bad_source_review_fails_before_commit(store):
    path=store.workspace/'source/jianying_mcp_project.json'
    manifest=json.loads(path.read_text())
    del manifest['plan']['clips'][0]['kind']
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError,match='source manifest'):
        batch_edit(store,'source','bad-source',[{'action':'edit','operations':[{'op':'remove','id':'a'}]}],False)
    assert not (store.workspace/'bad-source').exists()
