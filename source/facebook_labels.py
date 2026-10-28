"""Explicit Facebook UI labels (Vietnamese, English, French); no inferred targets."""
COMPOSER = ('write something', "what's on your mind", 'what’s on your mind',
            'bạn đang nghĩ', 'bạn viết gì', 'viết gì đó', 'viết bài', 'tạo bài viết', 'create post',
            'écrivez quelque chose', 'exprimez-vous', 'que voulez-vous dire',
            'à quoi pensez-vous', 'créer une publication')
EDITORS = ('tạo bài viết công khai', 'create a public post', 'create post',
           'anonymous post','create anonymous post','bài viết ẩn danh','tạo bài viết ẩn danh',
           'gửi bài viết ẩn danh','submit anonymous post','submit an anonymous post',
           'rédiger une publication anonyme',
           'publication anonyme','créer une publication anonyme',
           'créer une publication publique', 'créer une publication', 'créez une publication publique',
           'écrivez quelque chose', 'exprimez-vous', 'que voulez-vous dire', 'à quoi pensez-vous')
MEDIA = ('photo/video', 'photo / video', 'ảnh/video', 'ảnh / video', 'add photos',
         'thêm ảnh', 'upload', 'tải ảnh', 'add photo', 'photo/vidéo', 'photo / vidéo',
         'photos/vidéos', 'ajouter des photos', 'ajouter une photo', 'ajouter des photos/vidéos')
POST = {'post', 'đăng', 'publish', 'đăng bài', 'publier'}
FILE_NAMES = {'file name', 'tên tệp', 'tên tập tin', 'nom du fichier'}
POST_MENUS = ('hành động đối với bài viết', 'actions for this post',
              'actions pour cette publication', 'actions sur cette publication')
COMMENTS = ('viết bình luận', 'write a comment', 'comment as', 'bình luận dưới tên',
            'écrivez un commentaire', 'écrire un commentaire', 'commenter en tant que')
REPLIES = ('trả lời', 'reply', 'répondre', 'réponse')
EXPAND = {'xem thêm', 'see more', 'voir plus', 'en voir plus', 'afficher la suite'}
RECENT = {'vừa xong', 'just now', 'à l’instant', "à l'instant"}
APPROVAL = ('pending approval', 'awaiting approval', 'chờ phê duyệt', 'chờ duyệt',
            'đang chờ quản trị viên phê duyệt', 'đang chờ quản trị viên xét duyệt',
            'en attente d’approbation', "en attente d'approbation",
            'en attente de validation')
BLOCKED_FR = ('confirmez votre identité', 'activité inhabituelle',
              'temporairement bloqué', 'temporairement bloquée',
              'vous ne pouvez pas publier', 'vérification de sécurité', 'votre compte est restreint')
LINK_REJECTED = ('links are not allowed', 'link is not allowed', 'không cho phép liên kết',
                 'không cho phép đường liên kết', 'không được phép chứa liên kết',
                 'les liens ne sont pas autorisés', 'les liens ne sont pas autorisées',
                 'ce lien n’est pas autorisé', "ce lien n'est pas autorisé")

def caption_editor_allowed(role, name):
    """Never type post text into comment/reply, search, or credential controls."""
    excluded = COMMENTS + REPLIES + ('comment', 'bình luận', 'search', 'tìm kiếm',
                                    'rechercher', 'recherche', 'password', 'mot de passe')
    return role in {'edit', 'textbox', 'text box'} and not any(v in name for v in excluded)
