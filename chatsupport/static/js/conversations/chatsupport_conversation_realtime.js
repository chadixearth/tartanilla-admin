document.addEventListener('DOMContentLoaded', () => {
    const currentUserId = window.adminUserId;
    if (!currentUserId) return;

    // Real-time subscription for support_conversations and support_messages
    const conversationChannel = window.supabase
        .channel('support-conversations')
        .on('postgres_changes', {
            event: '*',
            schema: 'public',
            table: 'support_conversations',
            filter: `admin_id=eq.${currentUserId}`,
        }, handleConversationChange)
        .subscribe();

    const messageChannel = window.supabase
        .channel('support-messages')
        .on('postgres_changes', {
            event: '*',
            schema: 'public',
            table: 'support_messages'
        }, handleMessageChange)
        .subscribe();

    function handleConversationChange(payload) {
        // Reload conversations to update the list
        document.dispatchEvent(new Event('reloadSupportConversations'));
        
        // If this is the active conversation, also update the header status
        if (window.activeSupportConversationId === payload.new.id) {
            // Get the updated conversation's status
            const newStatus = payload.new.status;
            
            // Update the status display in the header
            const statusElement = document.querySelector('.chat-header p.font-medium');
            if (statusElement) {
                statusElement.textContent = newStatus;
                statusElement.className = `text-sm font-medium ${getStatusClass(newStatus)}`;
            }
            
            // If status changed to resolved/closed, add system message
            // if (payload.old && payload.old.status !== newStatus) {
            //     const messagesContainer = document.getElementById('messagesContainer');
            //     if (messagesContainer) {
            //         const systemMessage = document.createElement('div');
            //         systemMessage.className = 'py-1 px-4 flex justify-center';
            //         systemMessage.innerHTML = `
            //             <div class="py-1 px-3 rounded-full bg-gray-100 text-gray-600 text-xs">
            //                 Status changed to ${newStatus}
            //             </div>
            //         `;
            //         messagesContainer.appendChild(systemMessage);
            //         messagesContainer.scrollTop = messagesContainer.scrollHeight;
            //     }
            // }
        }
    }

    function handleMessageChange(payload) {
        document.dispatchEvent(new Event('reloadSupportConversations'));
    }

    // Helper function to get status color class
    function getStatusClass(status) {
        if (!status) return 'text-gray-500';
        
        switch(status.toLowerCase()) {
            case 'open': return 'text-green-600';
            case 'resolved': return 'text-blue-600';
            case 'closed': return 'text-gray-500';
            default: return 'text-gray-500';
        }
    }

    window.addEventListener('beforeunload', () => {
        window.supabase.removeChannel(conversationChannel);
        window.supabase.removeChannel(messageChannel);
    });
});