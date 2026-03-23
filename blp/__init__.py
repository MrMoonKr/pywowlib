from .python_blp import BlpConverter as BLP2PNG
from .python_blp import load_blp_image, load_blp_rgba

try:
    from .PNG2BLP.PNG2BLP import BlpFromPng as PNG2BLP
except ImportError:
    class PNG2BLP:
        def __init__(self, *args, **kwargs):
            raise NotImplementedError(
                "PNG2BLP native extension is not built. BLP writing remains optional."
            )
