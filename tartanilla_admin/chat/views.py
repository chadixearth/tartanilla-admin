from django.shortcuts import render

# Create your views here.# for testing purposes, we will create a chat view in the different app later
def chat_view(request):
    # For now, we'll just render a placeholder template
    return render(request, 'chat/chat.html')
