document.addEventListener('DOMContentLoaded', () => {
    // Modal Elements
    const newChatButton = document.querySelector('button.bg-\\[\\#561c24\\].text-white');
    const newChatModal = document.getElementById('newChatModal');
    const closeNewChatModal = document.getElementById('closeNewChatModal');
    
    // Tab Elements
    const driversTab = document.getElementById('driversTab');
    const ownersTab = document.getElementById('ownersTab');
    const driversList = document.getElementById('driversList');
    const ownersList = document.getElementById('ownersList');
    
    // Modal Open/Close
    if (newChatButton) {
        newChatButton.addEventListener('click', () => {
            newChatModal.classList.remove('hidden');
            // Dispatch event to fetch users
            document.dispatchEvent(new CustomEvent('fetchUsers'));
        });
    }
    
    if (closeNewChatModal) {
        closeNewChatModal.addEventListener('click', () => {
            newChatModal.classList.add('hidden');
        });
    }
    
    // Tab Switching
    if (driversTab && ownersTab) {
        driversTab.addEventListener('click', () => {
            switchTab('drivers');
        });
        
        ownersTab.addEventListener('click', () => {
            switchTab('owners');
        });
    }
    
    function switchTab(tab) {
        if (tab === 'drivers') {
            driversTab.classList.add('text-[#561c24]', 'border-b-2', 'border-[#561c24]');
            driversTab.classList.remove('text-gray-500');
            ownersTab.classList.add('text-gray-500');
            ownersTab.classList.remove('text-[#561c24]', 'border-b-2', 'border-[#561c24]');
            
            driversList.classList.remove('hidden');
            ownersList.classList.add('hidden');
        } else {
            ownersTab.classList.add('text-[#561c24]', 'border-b-2', 'border-[#561c24]');
            ownersTab.classList.remove('text-gray-500');
            driversTab.classList.add('text-gray-500');
            driversTab.classList.remove('text-[#561c24]', 'border-b-2', 'border-[#561c24]');
            
            ownersList.classList.remove('hidden');
            driversList.classList.add('hidden');
        }
    }
    
    // Listen for user selection events
    document.addEventListener('userSelected', async (event) => {
        const selectedUser = event.detail;
        const currentUserId = window.adminUserId;
        
        console.log('Selected user:', selectedUser);
        
        try {
            // 1. Check if conversation already exists
            const { data: existingConversations, error: checkError } = await window.supabase
                .from('conversations')
                .select('id')
                .or(`and(user1_id.eq.${currentUserId},user2_id.eq.${selectedUser.id}),and(user1_id.eq.${selectedUser.id},user2_id.eq.${currentUserId})`)
                .limit(1);
                
            if (checkError) throw checkError;
            
            let conversationId;
            
            if (existingConversations && existingConversations.length > 0) {
                // Use existing conversation
                conversationId = existingConversations[0].id;
                console.log('Using existing conversation:', conversationId);
            } else {
                // Create new conversation
                const { data: newConversation, error: createError } = await window.supabase
                    .from('conversations')
                    .insert([
                        { user1_id: currentUserId, user2_id: selectedUser.id }
                    ])
                    .select();
                    
                if (createError) throw createError;
                
                conversationId = newConversation[0].id;
                console.log('Created new conversation:', conversationId);
            }
            
            // Close the modal
            const newChatModal = document.getElementById('newChatModal');
            if (newChatModal) {
                newChatModal.classList.add('hidden');
            }
            
            // Trigger conversation selection (opens the chat)
            document.dispatchEvent(new CustomEvent('conversationSelected', {
                detail: { 
                    conversationId: conversationId,
                    otherUser: selectedUser 
                }
            }));
            
        } catch (error) {
            console.error('Error creating/finding conversation:', error);
            alert('Failed to start conversation. Please try again.');
        }
    });
});