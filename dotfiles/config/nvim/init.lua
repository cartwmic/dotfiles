-- bootstrap lazy.nvim, LazyVim and your plugins

require("config.lazy")

-- User Commands
vim.api.nvim_create_user_command("User_InsertPKMSFileTimestamp", function(_)
  local time = vim.fn.strftime("%Y-%m-%d-%H%M%S")
  local row, col = unpack(vim.api.nvim_win_get_cursor(0))
  vim.api.nvim_buf_set_text(0, row - 1, col, row - 1, col, { time })
end, {})
