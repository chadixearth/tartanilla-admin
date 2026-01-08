document.addEventListener('DOMContentLoaded', () => {
    // Listen for conversation selection (implement this event when a sidebar item is clicked)
    document.addEventListener('supportConversationSelected', async (event) => {
        const conversationId = event.detail.conversationId;
        const messagesContainer = document.getElementById('messagesContainer');
        if (!messagesContainer) return;

        messagesContainer.innerHTML = '<div class="text-center py-8 text-gray-500">Loading messages...</div>';

        // Fetch messages for the selected support conversation
        const { data: messages, error } = await window.supabase
            .from('support_messages')
            .select(`
                id,
                sender_id,
                message_text,
                created_at,
                is_read
            `)
            .eq('support_conversation_id', conversationId)
            .order('created_at', { ascending: true });

        if (error) {
            messagesContainer.innerHTML = '<div class="text-center py-4 text-red-500">Error loading messages</div>';
            return;
        }

        // Render messages
        messagesContainer.innerHTML = '';
        if (!messages || messages.length === 0) {
            messagesContainer.innerHTML = `
                <div class="flex flex-col items-center justify-center h-full text-center py-12">
                    <svg class="w-16 h-16 text-gray-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5"
                            d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                    </svg>
                    <h3 class="mt-2 text-sm font-medium text-gray-900">No messages yet</h3>
                    <p class="mt-1 text-sm text-gray-500">Start the conversation by sending a message below.</p>
                </div>
            `;
            return;
        }

        messages.forEach(msg => {
            const isCurrentUser = msg.sender_id === window.adminUserId;
            const msgDiv = document.createElement('div');
            msgDiv.className = `py-1 px-4 ${isCurrentUser ? 'flex justify-end' : ''}`;
            msgDiv.innerHTML = `
                <div class="max-w-[70%] rounded-lg p-3 ${isCurrentUser ? 'bg-[#561c24] text-white rounded-tr-none' : 'bg-gray-100 rounded-tl-none'}">
                    <p class="whitespace-pre-wrap break-words">${msg.message_text}</p>
                    <div class="text-xs mt-1 ${isCurrentUser ? 'text-gray-200' : 'text-gray-500'} text-right">
                        ${new Date(msg.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                        ${isCurrentUser ? `<span class="ml-1">${msg.is_read ? '✓✓' : '✓'}</span>` : ''}
                    </div>
                </div>
            `;
            messagesContainer.appendChild(msgDiv);
        });

        // Scroll to bottom
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    });
});