// Global Success/Error/Confirm Modal Utilities with Maroon Theme

// Global loading state management to prevent multiple clicks
let globalLoadingState = false;

function setGlobalLoading(isLoading) {
    globalLoadingState = isLoading;
    
    // Disable/enable all buttons with loading prevention
    const buttons = document.querySelectorAll('button[data-prevent-multiple], .prevent-multiple-clicks');
    buttons.forEach(btn => {
        btn.disabled = isLoading;
        if (isLoading) {
            btn.classList.add('opacity-50', 'cursor-not-allowed');
        } else {
            btn.classList.remove('opacity-50', 'cursor-not-allowed');
        }
    });
}

function isGlobalLoading() {
    return globalLoadingState;
}

// Utility function to add loading state to any button
function setButtonLoading(buttonId, isLoading, loadingText = 'Loading...') {
    const btn = document.getElementById(buttonId);
    const textSpan = btn?.querySelector('.btn-text') || btn;
    const loadingSpan = btn?.querySelector('.btn-loading');
    
    if (!btn) return;
    
    btn.disabled = isLoading;
    
    if (loadingSpan) {
        if (isLoading) {
            textSpan.classList.add('hidden');
            loadingSpan.classList.remove('hidden');
        } else {
            textSpan.classList.remove('hidden');
            loadingSpan.classList.add('hidden');
        }
    } else {
        btn.innerHTML = isLoading ? `<i class="fas fa-spinner fa-spin mr-2"></i>${loadingText}` : btn.getAttribute('data-original-text') || btn.innerHTML;
    }
}
function showSuccessModal(title, message, callback = null) {
    // Reset global loading state when showing success
    setGlobalLoading(false);
    
    const existingModal = document.getElementById('successModal');
    if (existingModal) {
        existingModal.remove();
    }

    const modalHTML = `
        <div id="successModal" class="fixed inset-0 bg-gray-900 bg-opacity-60 z-50 flex items-center justify-center p-4">
            <div class="bg-white rounded-2xl w-full max-w-md p-8 transform transition-all duration-300 scale-95 opacity-0 shadow-2xl">
                <div class="text-center">
                    <div class="mx-auto flex items-center justify-center h-20 w-20 rounded-full bg-gradient-to-br from-green-100 to-green-50 mb-6 shadow-lg">
                        <i class="fas fa-check-circle text-[#531B24] text-3xl"></i>
                    </div>
                    <h3 class="text-xl font-bold text-[#531B24] mb-3">${title}</h3>
                    <p class="text-gray-600 mb-8 leading-relaxed">${message}</p>
                    <button id="successModalClose" class="w-full bg-[#531B24] text-white px-6 py-3 rounded-xl hover:bg-[#6B2332] transition-all duration-200 font-semibold shadow-lg hover:shadow-xl transform hover:scale-105">
                        Continue
                    </button>
                </div>
            </div>
        </div>
    `;

    document.body.insertAdjacentHTML('beforeend', modalHTML);
    
    const modal = document.getElementById('successModal');
    const modalContent = modal.querySelector('div > div');
    
    setTimeout(() => {
        modalContent.classList.remove('scale-95', 'opacity-0');
        modalContent.classList.add('scale-100', 'opacity-100');
    }, 10);

    function closeModal() {
        modalContent.classList.add('scale-95', 'opacity-0');
        modalContent.classList.remove('scale-100', 'opacity-100');
        setTimeout(() => {
            modal.remove();
            if (callback) callback();
        }, 300);
    }

    document.getElementById('successModalClose').addEventListener('click', closeModal);
    modal.addEventListener('click', (e) => {
        if (e.target === modal) closeModal();
    });
    
    const escHandler = (e) => {
        if (e.key === 'Escape') {
            closeModal();
            document.removeEventListener('keydown', escHandler);
        }
    };
    document.addEventListener('keydown', escHandler);
    
    setTimeout(() => {
        document.getElementById('successModalClose')?.focus();
    }, 400);
}

function showErrorModal(title, message) {
    // Reset global loading state when showing error
    setGlobalLoading(false);
    
    const existingModal = document.getElementById('errorModal');
    if (existingModal) {
        existingModal.remove();
    }

    const modalHTML = `
        <div id="errorModal" class="fixed inset-0 bg-gray-900 bg-opacity-60 z-50 flex items-center justify-center p-4">
            <div class="bg-white rounded-2xl w-full max-w-md p-8 transform transition-all duration-300 scale-95 opacity-0 shadow-2xl">
                <div class="text-center">
                    <div class="mx-auto flex items-center justify-center h-20 w-20 rounded-full bg-gradient-to-br from-red-100 to-red-50 mb-6 shadow-lg">
                        <i class="fas fa-exclamation-triangle text-red-600 text-3xl"></i>
                    </div>
                    <h3 class="text-xl font-bold text-[#531B24] mb-3">${title}</h3>
                    <p class="text-gray-600 mb-8 leading-relaxed">${message}</p>
                    <button id="errorModalClose" class="w-full bg-red-600 text-white px-6 py-3 rounded-xl hover:bg-red-700 transition-all duration-200 font-semibold shadow-lg hover:shadow-xl transform hover:scale-105">
                        Try Again
                    </button>
                </div>
            </div>
        </div>
    `;

    document.body.insertAdjacentHTML('beforeend', modalHTML);
    
    const modal = document.getElementById('errorModal');
    const modalContent = modal.querySelector('div > div');
    
    setTimeout(() => {
        modalContent.classList.remove('scale-95', 'opacity-0');
        modalContent.classList.add('scale-100', 'opacity-100');
    }, 10);

    function closeModal() {
        modalContent.classList.add('scale-95', 'opacity-0');
        modalContent.classList.remove('scale-100', 'opacity-100');
        setTimeout(() => modal.remove(), 300);
    }

    document.getElementById('errorModalClose').addEventListener('click', closeModal);
    modal.addEventListener('click', (e) => {
        if (e.target === modal) closeModal();
    });
}

function showFailModal(title, message, callback = null) {
    // Reset global loading state when showing fail modal
    setGlobalLoading(false);
    
    const existingModal = document.getElementById('failModal');
    if (existingModal) {
        existingModal.remove();
    }

    const modalHTML = `
        <div id="failModal" class="fixed inset-0 bg-gray-900 bg-opacity-60 z-50 flex items-center justify-center p-4">
            <div class="bg-white rounded-2xl w-full max-w-md p-8 transform transition-all duration-300 scale-95 opacity-0 shadow-2xl">
                <div class="text-center">
                    <div class="mx-auto flex items-center justify-center h-20 w-20 rounded-full bg-gradient-to-br from-red-100 to-red-50 mb-6 shadow-lg">
                        <i class="fas fa-times-circle text-red-600 text-3xl"></i>
                    </div>
                    <h3 class="text-xl font-bold text-[#531B24] mb-3">${title}</h3>
                    <p class="text-gray-600 mb-8 leading-relaxed">${message}</p>
                    <button id="failModalClose" class="w-full bg-red-600 text-white px-6 py-3 rounded-xl hover:bg-red-700 transition-all duration-200 font-semibold shadow-lg hover:shadow-xl transform hover:scale-105">
                        Close
                    </button>
                </div>
            </div>
        </div>
    `;

    document.body.insertAdjacentHTML('beforeend', modalHTML);
    
    const modal = document.getElementById('failModal');
    const modalContent = modal.querySelector('div > div');
    
    setTimeout(() => {
        modalContent.classList.remove('scale-95', 'opacity-0');
        modalContent.classList.add('scale-100', 'opacity-100');
    }, 10);

    function closeModal() {
        modalContent.classList.add('scale-95', 'opacity-0');
        modalContent.classList.remove('scale-100', 'opacity-100');
        setTimeout(() => {
            modal.remove();
            if (callback) callback();
        }, 300);
    }

    document.getElementById('failModalClose').addEventListener('click', closeModal);
    modal.addEventListener('click', (e) => {
        if (e.target === modal) closeModal();
    });
    
    const escHandler = (e) => {
        if (e.key === 'Escape') {
            closeModal();
            document.removeEventListener('keydown', escHandler);
        }
    };
    document.addEventListener('keydown', escHandler);
    
    setTimeout(() => {
        document.getElementById('failModalClose')?.focus();
    }, 400);
}

function showConfirmModal(message, onConfirm, onCancel = null) {
    const existingModal = document.getElementById('confirmModal');
    if (existingModal) {
        existingModal.remove();
    }

    const modalHTML = `
        <div id="confirmModal" class="fixed inset-0 bg-gray-900 bg-opacity-60 z-50 flex items-center justify-center p-4">
            <div class="bg-white rounded-2xl w-full max-w-md p-8 transform transition-all duration-300 scale-95 opacity-0 shadow-2xl">
                <div class="text-center">
                    <div class="mx-auto flex items-center justify-center h-20 w-20 rounded-full bg-gradient-to-br from-yellow-100 to-yellow-50 mb-6 shadow-lg">
                        <i class="fas fa-question-circle text-[#531B24] text-3xl"></i>
                    </div>
                    <h3 class="text-xl font-bold text-[#531B24] mb-3">Confirm Action</h3>
                    <p class="text-gray-600 mb-8 leading-relaxed">${message}</p>
                    <div class="flex gap-3">
                        <button id="confirmModalCancel" class="flex-1 bg-gray-200 text-gray-700 px-6 py-3 rounded-xl hover:bg-gray-300 transition-all duration-200 font-semibold">
                            Cancel
                        </button>
                        <button id="confirmModalConfirm" class="flex-1 bg-[#531B24] text-white px-6 py-3 rounded-xl hover:bg-[#6B2332] transition-all duration-200 font-semibold shadow-lg hover:shadow-xl transform hover:scale-105">
                            Confirm
                        </button>
                    </div>
                </div>
            </div>
        </div>
    `;

    document.body.insertAdjacentHTML('beforeend', modalHTML);
    
    const modal = document.getElementById('confirmModal');
    const modalContent = modal.querySelector('div > div');
    
    setTimeout(() => {
        modalContent.classList.remove('scale-95', 'opacity-0');
        modalContent.classList.add('scale-100', 'opacity-100');
    }, 10);

    function closeModal() {
        modalContent.classList.add('scale-95', 'opacity-0');
        modalContent.classList.remove('scale-100', 'opacity-100');
        setTimeout(() => modal.remove(), 300);
    }

    document.getElementById('confirmModalConfirm').addEventListener('click', () => {
        closeModal();
        if (onConfirm) onConfirm();
    });
    
    document.getElementById('confirmModalCancel').addEventListener('click', () => {
        closeModal();
        if (onCancel) onCancel();
    });

    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            closeModal();
            if (onCancel) onCancel();
        }
    });
}