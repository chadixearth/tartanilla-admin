document.addEventListener('DOMContentLoaded', () => {
    const driversList = document.getElementById('driversList');
    const ownersList = document.getElementById('ownersList');
    
    // Listen for the fetchUsers event
    document.addEventListener('fetchUsers', fetchUsers);
    
    // Fetch Users from Supabase
    async function fetchUsers() {
        try {
            // Reset lists
            driversList.innerHTML = '<div class="text-center py-8 text-gray-500">Loading drivers...</div>';
            ownersList.innerHTML = '<div class="text-center py-8 text-gray-500">Loading owners...</div>';
            
            // Fetch users from Supabase
            const { data: drivers, error: driversError } = await window.supabase
                .from('users')
                .select('id, name, email, profile_photo_url')
                .eq('role', 'driver');
                
            const { data: owners, error: ownersError } = await window.supabase
                .from('users')
                .select('id, name, email, profile_photo_url')
                .eq('role', 'owner');
            
            if (driversError) throw driversError;
            if (ownersError) throw ownersError;
            
            // Render users
            renderUserList(driversList, drivers || []);
            renderUserList(ownersList, owners || []);
            
        } catch (error) {
            console.error('Error fetching users:', error);
            driversList.innerHTML = '<div class="text-center py-4 text-red-500">Error loading drivers</div>';
            ownersList.innerHTML = '<div class="text-center py-4 text-red-500">Error loading owners</div>';
        }
    }
    
    // Render User List
    function renderUserList(container, users) {
        if (!users.length) {
            container.innerHTML = '<div class="text-center py-4 text-gray-500">No users found</div>';
            return;
        }
        
        container.innerHTML = '';
        users.forEach(user => {
            const userEl = document.createElement('div');
            userEl.className = 'p-3 border border-gray-200 rounded-lg hover:bg-gray-50 flex items-center space-x-3 cursor-pointer';
            
            // Set default image path if profile_photo_url is null
            const profileImg = user.profile_photo_url || '/static/img/TarTrack Logo_sakto.png';
            
            userEl.innerHTML = `
                <div class="flex-shrink-0">
                    <img src="${profileImg}" 
                         alt="${user.name}" 
                         class="w-10 h-10 rounded-full object-cover"
                         onerror="this.src='/static/img/TarTrack Logo_sakto.png'">
                </div>
                <div class="flex-1 min-w-0">
                    <p class="text-sm font-medium text-[#561c24] truncate">${user.name}</p>
                    <p class="text-xs text-gray-500 truncate">${user.email}</p>
                </div>
            `;
            
            userEl.addEventListener('click', () => {
                // Dispatch custom event with user data
                document.dispatchEvent(new CustomEvent('userSelected', {
                    detail: user
                }));
            });
            
            container.appendChild(userEl);
        });
    }
});