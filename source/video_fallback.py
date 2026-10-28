"""Conservative pre-submit video fallback. Unknown outcomes never permit a second post."""
import re
from pathlib import Path
from media import paths,resolve,validate_file
from facebook_labels import EDITORS, caption_editor_allowed
REJECTIONS=("couldn't upload your video","could not upload your video","unable to upload video","video upload failed","video is too large","video file is too large","video format is not supported","unsupported video format","không thể tải video lên","tải video lên không thành công","video quá lớn","tệp video quá lớn","định dạng video không được hỗ trợ")
REJECTIONS += ('impossible d’importer votre vidéo', "impossible d'importer votre vidéo",
               'impossible de télécharger votre vidéo', 'votre vidéo est trop volumineuse',
               'le fichier vidéo est trop volumineux', 'format vidéo non pris en charge')
REMOVE={'remove video','delete video','xóa video','gỡ video','supprimer la vidéo','retirer la vidéo'}

def rejection(snapshot,caption):
    text=re.sub(r'\s+',' ',snapshot).casefold();body=re.sub(r'\s+',' ',caption).casefold()
    return next((phrase for phrase in REJECTIONS if phrase in text and phrase not in body),'')

def editor_present(targets):
    return any(caption_editor_allowed(t.get('role'),t.get('name','')) and any(t.get('name','').startswith(s) for s in EDITORS) for t in targets)

def removal_target(snapshot,targets,caption,*,submitted,attached,has_video,used):
    if submitted or not attached or not has_video or used or not rejection(snapshot,caption):return None
    if not editor_present(targets) or re.sub(r'\s+',' ',caption).casefold()[:100] not in re.sub(r'\s+',' ',snapshot).casefold():return None
    matches=[t for t in targets if t.get('role')=='button' and t.get('name') in REMOVE]
    return matches[0] if len(matches)==1 else None

def photo_paths(value,directory):
    names=[];base=Path(directory).resolve()
    for item in paths(value):
        path=Path(item).resolve()
        if path.parent!=base or not path.is_file() or validate_file(path)!='image':raise ValueError('Ảnh dự phòng không hợp lệ trong kho.')
        names.append(path.name)
    if not names:raise ValueError('Video bị từ chối nhưng chưa có ảnh dự phòng cùng game. Thêm ảnh và phân loại rồi tạo lịch mới.')
    return paths(resolve(names,base))

def removal_confirmed(snapshot,targets,caption):
    return (editor_present(targets) and not rejection(snapshot,caption)
            and not any(t.get('role')=='button' and t.get('name') in REMOVE for t in targets)
            and re.sub(r'\s+',' ',caption).casefold()[:100] in re.sub(r'\s+',' ',snapshot).casefold())
