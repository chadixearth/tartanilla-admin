from django.shortcuts import render, redirect
from django.views import View
from django.views.decorators.cache import never_cache
from django.utils.decorators import method_decorator
from accounts.views import admin_authenticated

class ChatSupportView(View):
    template_name = "chatsupport/chat_support.html"
    
    @method_decorator(never_cache)
    @method_decorator(admin_authenticated)
    def dispatch(self, request, *args, **kwargs):
        return super().dispatch(request, *args, **kwargs)
    
    def get(self, request):
        admin_user_id = request.COOKIES.get('admin_user_id', '')
        return render(request, self.template_name, {'admin_user_id': admin_user_id})
