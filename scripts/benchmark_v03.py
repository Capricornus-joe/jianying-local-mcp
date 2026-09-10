"""Real stdio benchmark, synthetic media only; all generated projects auto-clean."""
from __future__ import annotations
import asyncio
from datetime import timedelta
import json
import os
from pathlib import Path
import statistics
import sys
import tempfile
import time
import wave
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

PACKAGE = Path(__file__).resolve().parents[1]

def payload(response):
    if response.structuredContent is not None:
        return response.structuredContent
    return json.loads(next(part.text for part in response.content if part.type == 'text'))

async def run_round(root, index):
    work = root/f'round-{index}'
    work.mkdir()
    media = work/'synthetic.wav'
    with wave.open(str(media), 'wb') as out:
        out.setparams((1,2,48000,0,'NONE','not compressed'))
        out.writeframes(b'\0\0'*48000*105)
    clips = [{'id':f't{i}', 'kind':'text','text':f'第{i}句测试字幕', 'track':'字幕','start':i,'duration':1} for i in range(100)]
    clips.append({'id':'audio','kind':'audio','path':str(media),'track':'配乐','start':0,'duration':100})
    env=dict(os.environ, PYTHONPATH=str(PACKAGE), JIANYING_MCP_WORKSPACE=str(work/'projects'))
    params=StdioServerParameters(command=sys.executable,args=['-m','jianying_local_mcp','serve'],env=env,cwd=str(PACKAGE))
    actions=[
        ('edit_draft', {'operations':[{'op':'update','id':'t0','changes':{'text':'修改后的字幕'}}]}, 'edit'),
        ('set_clip_features', {'clip_ids':['t0'],'features':{'text_style':{'bold':True}}}, 'features'),
        ('apply_motion_preset', {'clip_ids':['t0'],'preset':'fade_in','strength':.2}, 'motion'),
        ('style_subtitles', {'track':'字幕','style':{'font_size':42}}, 'style_subtitles'),
        ('set_clip_features', {'clip_ids':['t0'],'features':{'text_style':{'stroke_color':'#000000','stroke_width':2}}}, 'features'),
    ]
    async with stdio_client(params) as (reader,writer):
        async with ClientSession(reader,writer,read_timeout_seconds=timedelta(seconds=30)) as session:
            await session.initialize()
            async def call(tool,args):
                response=await session.call_tool(tool,args)
                assert not response.isError,response.content
                return response
            source=await call('create_draft',{'plan':{'name':'source','clips':clips},'dry_run':False})
            assert 'plan' not in payload(source)
            started=time.perf_counter();responses=[];name='source'
            for i,(tool,args,_) in enumerate(actions):
                new=f'seq-{i}'
                responses.append(await call(tool,dict(args,name=name,new_name=new,dry_run=False,include_plan=True)))
                name=new
            sequential_seconds=time.perf_counter()-started
            started=time.perf_counter()
            batch=await call('batch_edit',{'name':'source','new_name':'batched',
                'steps':[dict(args,action=action) for _,args,action in actions], 'dry_run':False})
            batch_seconds=time.perf_counter()-started
            assert 'plan' not in payload(batch)
            # Read only after timings. Canonicalize copied paths for semantic comparison.
            seq=payload(await call('read_managed_project',{'name':name,'view':'full'}))
            bat=payload(await call('read_managed_project',{'name':'batched','view':'full'}))
            def normalized(plan):
                values=json.loads(json.dumps(plan['clips']))
                for c in values:
                    if 'path' in c:c['path']=Path(c['path']).name
                return values
            assert normalized(seq)==normalized(bat)
            # Invalid final step must not create an intermediate or final project.
            before=set((work/'projects').iterdir())
            failure=await session.call_tool('batch_edit',{'name':'source','new_name':'must-not-exist',
                'steps':[dict(actions[0][1],action='edit'),{'action':'features','clip_ids':['absent'],'features':{'transform':{'x':.1}}}],
                'dry_run':False})
            assert failure.isError and set((work/'projects').iterdir())==before
            page=payload(await call('read_managed_project',{'name':'batched','view':'clips','limit':5,'track':'字幕'}))
            assert len(page['clips'])==5
            def resources(p):return sum(x.stat().st_size for x in (p/'Resources').rglob('*') if x.is_file())
            seq_bytes=sum(resources(work/'projects'/f'seq-{i}') for i in range(len(actions)))
            batch_bytes=resources(work/'projects'/'batched')
            return {'sequential_seconds':sequential_seconds,'batch_seconds':batch_seconds,
                'sequential_tool_calls':5,'batch_tool_calls':1,
                'sequential_revision_count':5,'batch_revision_count':1,
                'sequential_media_bytes':seq_bytes,'batch_media_bytes':batch_bytes,
                'sequential_response_bytes':sum(len(r.model_dump_json().encode()) for r in responses),
                'batch_response_bytes':len(batch.model_dump_json().encode()),
                'final_clip_semantics_equal':True,'failed_batch_no_writes':True,'default_compact_and_pagination_verified':True}

async def main():
    with tempfile.TemporaryDirectory(prefix='jianying-mcp-benchmark-') as directory:
        results=[await run_round(Path(directory),i) for i in range(3)]
    numeric=[k for k,v in results[0].items() if isinstance(v,(int,float)) and not isinstance(v,bool)]
    medians={k:statistics.median(r[k] for r in results) for k in numeric}
    report={'scope':'3 rounds of real MCP stdio;100 synthetic captions plus105s silent WAV;five ordered changes. Excludes app launch/render/export, client startup,model latency and source creation. Sequential is current implementation with legacy five-save/full-result usage, not an archived old binary.',
            'rounds':results,'medians':medians,'temporary_projects_removed':True,
            'response_measure':'UTF-8 serialized MCP CallToolResult bytes (text plus structured content), not billed tokens',
            'wall_speedup':medians['sequential_seconds']/medians['batch_seconds'],
            'response_reduction_percent':100*(1-medians['batch_response_bytes']/medians['sequential_response_bytes'])}
    dest=PACKAGE/'docs/performance-v03.json'
    dest.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':asyncio.run(main())
