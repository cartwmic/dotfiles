-- bootstrap lazy.nvim, LazyVim and your plugins

require("config.lazy")

-- User Commands
vim.api.nvim_create_user_command("UserPutPKMSFileDateTimestampToClipboard", function(_)
  local time = vim.fn.strftime("%Y-%m-%d-%H%M%S")
  vim.fn.setreg("+", time)
end, {})

vim.api.nvim_create_user_command("UserPutCurrentTimestampToClipboard", function(_)
  local time = vim.fn.strftime("%H:%M:%S")
  vim.fn.setreg("+", time)
end, {})
