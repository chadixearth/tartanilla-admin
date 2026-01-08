from urllib import request
from django.shortcuts import render, redirect
from django.views import View
from django.utils.decorators import method_decorator
from accounts.views import admin_authenticated

class ChatView(View):
    template_name = "chat/chat.html"
    
    @method_decorator(admin_authenticated)
    def dispatch(self, request, *args, **kwargs):
        return super().dispatch(request, *args, **kwargs)
    
    def get(self, request):
        admin_user_id = request.COOKIES.get('admin_user_id', '')
        
        # Redirect if no user ID is found
        if not admin_user_id:
            return redirect('login_view')
            
        return render(request, self.template_name, {'admin_user_id': admin_user_id})

