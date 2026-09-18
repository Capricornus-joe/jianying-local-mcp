"""MCP transport. All writes create new managed projects in an explicit workspace."""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .core import ProjectStore, environment_status, inspect_draft
from .media import probe_media
from .subtitles import parse_srt
from .publishing import publish_project
from .advanced import MOTION_PRESETS, apply_motion, update_clip_features
from . import workflow
from . import processing
from .resources import list_resources, resolve_resource
from .batch import batch_edit as run_batch_edit
from .responses import compact_result, project_view

mcp = FastMCP(
    "Jianying Local MCP",
    instructions=("Create local, self-contained, editable Mac Jianying draft packages. "
                  "Native application compatibility is experimental until validated in the installed version. "
                  "Use dry_run to inspect planned work. Revisions always use a new name; never overwrite source drafts. "
                  "Only managed projects can be edited. Encrypted native drafts are explicitly unsupported. "
                  "Prefer batch_edit for multiple related edits: it saves once without intermediate projects. "
                  "Results are compact by default; request include_plan=true only for programmatic inspection. "
                  "read_managed_project defaults to summary; use view=clips with pagination to obtain IDs. "
                  "There is no native auto-export tool in this version. All times are seconds."),
    log_level="WARNING",
)
READ = ToolAnnotations(
    readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False,
)
# Writes can create new projects or unique media outputs, so retries are not guaranteed idempotent.
WRITE = ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False,
)


@mcp.tool(annotations=READ)
def check_environment() -> dict:
    """Detect the installed app, local draft folder, implemented features and limitations."""
    return environment_status()


@mcp.tool(annotations=READ)
def inspect_media(path: str) -> dict:
    """Read duration, resolution and audio presence of an absolute local media path; no uploads."""
    return probe_media(path)


@mcp.tool(annotations=READ)
def read_native_draft(path: str) -> dict:
    """Inspect a plaintext native draft directory/file without changing it. Encoded drafts return unsupported."""
    return inspect_draft(path)


@mcp.tool(annotations=READ)
def list_managed_projects() -> dict:
    """List only projects authored by this MCP in its configured workspace."""
    store = ProjectStore()
    return {"workspace": str(store.workspace), "projects": store.list_projects()}


@mcp.tool(annotations=READ)
def read_managed_project(name: str, view: str = 'summary', offset: int = 0,
                         limit: int = 50, track: str | None = None) -> dict:
    """Read a compact summary; view=clips returns paged clip IDs/timing (limit<=200).
    Use track to filter a clip page. view=full explicitly returns the complete plan.
    """
    return project_view(ProjectStore().load_managed(name), view, offset, limit, track)


@mcp.tool(annotations=WRITE)
def batch_edit(name: str, new_name: str, steps: list[dict], dry_run: bool = True, include_plan: bool = False) -> dict:
    """Apply 1-100 ordered editing steps in memory, then save ONE new revision.

    Each step has action plus the fields of its corresponding tool:
    edit(operations), features(clip_ids,features), motion(clip_ids,preset,strength?),
    subtitles(content,track?,offset?,font_size?,color?),
    style_subtitles(style,track?,clip_ids?), reorder(track,clip_ids,start?),
    ripple_delete(start,end). No intermediate project or media copies are created.
    Invalid steps abort before any project write. Does not publish or export.
    """
    return compact_result(run_batch_edit(ProjectStore(), name, new_name, steps, dry_run), include_plan)


@mcp.tool(annotations=WRITE)
def create_draft(plan: dict, dry_run: bool = True, include_plan: bool = False) -> dict:
    """Validate/build a new self-contained Mac draft; does not register it in the native app.

    plan fields: name, width=1920, height=1080, fps=30, clips=[].
    Each clip: id(optional unique ASCII), kind(video/audio/image/text), track,
    start, duration. Media requires absolute path, optional source_start=0,
    speed=1, volume=1. Text requires text, optional font_size=48, color=#FFFFFF,
    x=0,y=-0.75. Coordinates are normalized; font size has an experimental /6
    mapping to native schema units. Same-track overlaps are rejected; overlays
    need separate tracks. Duration is timeline seconds, source duration=duration*speed.
    dry_run=True writes nothing; false copies media and writes a new project.
    """
    return compact_result(ProjectStore().create(plan, dry_run=dry_run), include_plan)


@mcp.tool(annotations=WRITE)
def edit_draft(name: str, new_name: str, operations: list[dict], dry_run: bool = True, include_plan: bool = False) -> dict:
    """Create a new revision of an MCP-managed project; source always remains unchanged.

    Operations: {op:append,clip:{...}}, {op:remove,id:clip_id},
    {op:update,id:clip_id,changes:{start,duration,source_start,speed,volume,text,...}},
    {op:split,id:clip_id,at:timeline_seconds}. Trim/move through update; gaps are
    preserved and there is no implicit ripple editing. Get IDs using read_managed_project.
    """
    return compact_result(ProjectStore().edit(name, new_name, operations, dry_run=dry_run), include_plan)


@mcp.tool(annotations=WRITE)
def add_srt(name: str, new_name: str, content: str, track: str = "字幕",
            offset: float = 0, font_size: float = 48, color: str = "#FFFFFF",
            dry_run: bool = True, include_plan: bool = False) -> dict:
    """Import SRT text into a new managed revision. Invalid cues fail explicitly; no partial import."""
    clips = parse_srt(content, track=track, offset=offset, font_size=font_size, color=color)
    if not clips:
        raise ValueError("SRT contains no cues")
    return compact_result(ProjectStore().edit(name, new_name, [{"op": "append", "clip": c} for c in clips], dry_run=dry_run), include_plan)


@mcp.tool(annotations=WRITE)
def publish_draft(name: str, draft_root: str, dry_run: bool = True) -> dict:
    """Add a managed revision as a NEW native draft and register it on Jianying's home page.

    draft_root must be the absolute existing com.lveditor.draft folder with a
    recognized plaintext root_meta_info.json. Fully quit Jianying first and
    keep it closed until a real publication finishes. Defaults to no-write
    validation. Existing drafts are never replaced; the index is backed up.
    Native edits are not synced back to the managed source. Publishing does
    not launch the app or export video. Requires native folder write access.
    """
    return publish_project(ProjectStore(), name, draft_root, dry_run=dry_run)


@mcp.tool(annotations=READ)
def list_motion_presets() -> dict:
    """List local linear motion recipes; native exported behavior has version-specific limits."""
    return {'presets':MOTION_PRESETS, 'easing':'linear',
            'opacity_warning':'Alpha keyframes may preview correctly but be ignored by native export; verify the result.'}


@mcp.tool(annotations=WRITE)
def set_clip_features(name: str, new_name: str, clip_ids: list[str], features: dict,
                      dry_run: bool = True, include_plan: bool = False) -> dict:
    """Apply advanced controls to selected clips in a new revision.

    Groups: transform {x,y,scale_x,scale_y,rotation,opacity,flip_horizontal,flip_vertical};
    crop {left,top,right,bottom} normalized source bounds; text_style supports bold,
    italic,underline,alignment,stroke_color,stroke_width,background_color,
    background_opacity,background_radius,shadow_color,shadow_opacity,shadow_diffuse,
    shadow_distance,shadow_angle,letter_spacing,line_spacing;
    keyframes {x|y|scale_x|scale_y|rotation|opacity:[{time,value}]} with clip-relative
    seconds and linear interpolation; audio_fade {in,out} seconds.
    mask {shape:circle|rectangle|linear,x,y,width,height,rotation,feather:0..100,
    invert,round_corner:0..100}; circle width defaults to compensate aspect ratio.
    animations [{type:in|out|group,duration,resource:{name,effect_id,resource_id,path}}];
    transition_out {duration,resource:{name,effect_id,resource_id,path,is_overlap}}.
    Features merge per group for transform/style/keyframes; others replace.
    Pass null for a group to remove it. Resolve downloaded native resources first.
    """
    return compact_result(update_clip_features(ProjectStore(),name,new_name,clip_ids,features,dry_run), include_plan)


@mcp.tool(annotations=WRITE)
def apply_motion_preset(name:str,new_name:str,clip_ids:list[str],preset:str,
                        strength:float=.15,dry_run:bool=True, include_plan: bool = False)->dict:
    """Create clip-relative motion keyframes: zoom_in/out, pan_left/right, slide_up/down,
    fade_in/out, pulse. Existing keyframes on the same properties are replaced.
    Alpha animation requires exported-frame verification in your installed app.
    """
    return compact_result(apply_motion(ProjectStore(),name,new_name,clip_ids,preset,strength,dry_run), include_plan)


@mcp.tool(annotations=WRITE)
def reorder_track(name:str,new_name:str,track:str,clip_ids:list[str],start:float=0,
                  dry_run:bool=True, include_plan: bool = False)->dict:
    """Reorder ALL clips of one track into a gapless sequence; other tracks remain unchanged."""
    return compact_result(workflow.reorder_track(ProjectStore(),name,new_name,track,clip_ids,start,dry_run), include_plan)


@mcp.tool(annotations=WRITE)
def ripple_delete(name:str,new_name:str,start:float,end:float,dry_run:bool=True, include_plan: bool = False)->dict:
    """Delete a timeline interval from all tracks, trim crossing clips and close the gap.
    Source in-points account for playback speed. Animated intervals may be rejected.
    """
    return compact_result(workflow.ripple_delete(ProjectStore(),name,new_name,start,end,dry_run), include_plan)


@mcp.tool(annotations=WRITE)
def style_subtitles(name:str,new_name:str,style:dict,track:str|None=None,
                    clip_ids:list[str]|None=None,dry_run:bool=True, include_plan: bool = False)->dict:
    """Batch update subtitle font_size/color/x/y by track or clip IDs, in a new revision."""
    return compact_result(workflow.style_subtitles(ProjectStore(),name,new_name,style,track,clip_ids,dry_run), include_plan)


@mcp.tool(annotations=READ)
def export_srt(name:str,track:str|None=None)->dict:
    """Return a managed project's subtitles as SRT text; does not write or upload files."""
    return workflow.export_srt(ProjectStore(),name,track)


@mcp.tool(annotations=WRITE)
def montage_create(name:str,paths:list[str],clip_duration:float|None=None,
                   image_duration:float=3,track:str='主画面',width:int=1920,
                   height:int=1080,fps:float=30,dry_run:bool=True, include_plan: bool = False)->dict:
    """Assemble local videos/photos in order. None uses full video lengths; audio-only inputs fail.
    Fixed duration uses the shorter of requested and source length. Copies all media into a new draft.
    """
    return compact_result(workflow.montage_create(ProjectStore(),name,paths,clip_duration,image_duration,
                                   track,width,height,fps,dry_run), include_plan)


@mcp.tool(annotations=WRITE)
def process_media(path:str,output_dir:str,operations:dict,dry_run:bool=True)->dict:
    """Create NEW media with baked local effects: brightness[-1,1],contrast[0,3],
    saturation[0,3],gamma[0.1,10],reverse,extract_audio,normalize_audio,denoise_audio.
    Boolean operations use true/false. Source is untouched; this is preprocessing,
    not editable native adjustment parameters. Reverse limit 10 minutes.
    Output has a unique filename and can be reused with create_draft or montage_create.
    """
    return processing.process_media(path,output_dir,operations,dry_run)


@mcp.tool(annotations=WRITE)
def extract_frame(path:str,time:float,output_dir:str,dry_run:bool=True)->dict:
    """Extract a NEW PNG at a source time for inspection, covers or freeze frames.
    Add the output as an image clip to hold it for any desired timeline duration.
    """
    return processing.extract_frame(path,time,output_dir,dry_run)


@mcp.tool(annotations=READ)
def list_native_resources(kind:str='all',query:str='',cache_root:str|None=None)->dict:
    """Find reviewed native video/text animations and transitions in the local effect cache.
    kind: all, animation, video_animation, text_animation, transition. Cache presence
    and public catalog pricing do not prove current account entitlement or playback.
    No effect scripts execute here and nothing is downloaded.
    """
    return list_resources(kind,query,cache_root)


@mcp.tool(annotations=WRITE)
def apply_native_resource(name:str,new_name:str,clip_ids:list[str],resource_kind:str,
                          resource_name:str,duration:float=.5,dry_run:bool=True, include_plan: bool = False)->dict:
    """Apply one uniquely cached catalog-free transition or entrance/exit animation.
    resource_kind is transition/video_animation/text_animation; resource_name is
    an exact name from list_native_resources. A transition attaches to the outgoing
    visual clip. Animation replaces the same phase while preserving its other phase.
    This creates a new managed revision and never downloads resources.
    """
    from copy import deepcopy
    if resource_kind not in {'transition','video_animation','text_animation'}:
        raise ValueError('Specify transition, video_animation or text_animation')
    if not isinstance(clip_ids,list) or not clip_ids or len(set(clip_ids))!=len(clip_ids):
        raise ValueError('clip_ids must be a nonempty unique list')
    resource=resolve_resource(resource_kind,resource_name)
    fields={'name','effect_id','resource_id','path','category_id','category_name','is_overlap'}
    descriptor={k:v for k,v in resource.items() if k in fields}
    store=ProjectStore();plan=deepcopy(store.load_managed(name));plan['name']=new_name
    if set(clip_ids)-{c['id'] for c in plan['clips']}: raise ValueError('Unknown clip IDs')
    for clip in plan['clips']:
        if clip['id'] not in clip_ids: continue
        if resource_kind=='text_animation' and clip['kind']!='text': raise ValueError('Text resource needs text clips')
        if resource_kind!='text_animation' and clip['kind'] not in {'video','image'}: raise ValueError('Video resources need videos/images')
        if resource_kind=='transition':
            clip['transition_out']={'duration':duration,'resource':descriptor}
        else:
            phase=resource['animation_type']
            animations=[a for a in clip.get('animations',[]) if a['type']!=phase]
            animations.append({'type':phase,'duration':duration,'resource':descriptor})
            clip['animations']=animations
    return compact_result(store.create(plan,dry_run=dry_run), include_plan)


def run() -> None:
    mcp.run(transport="stdio")
