const searchInput = element.querySelector('#lut-color-search');
const clearBtn = element.querySelector('#lut-color-search-clear');

if (searchInput) {
  searchInput.oninput = () => {
    if (window.filterLutColors) {
      window.filterLutColors(searchInput.value);
    }
  };
  searchInput.onfocus = () => {
    searchInput.style.borderColor = '#2196F3';
  };
  searchInput.onblur = () => {
    searchInput.style.borderColor = '#ddd';
  };
}

if (clearBtn && searchInput) {
  clearBtn.onmouseover = () => {
    clearBtn.style.background = '#e0e0e0';
  };
  clearBtn.onmouseout = () => {
    clearBtn.style.background = '#f5f5f5';
  };
  clearBtn.onclick = () => {
    searchInput.value = '';
    if (window.filterLutColors) {
      window.filterLutColors('');
    }
  };
}

if (window.filterLutColors) {
  window.filterLutColors(searchInput ? searchInput.value : '');
}
