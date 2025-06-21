-- Keymaps are automatically loaded on the VeryLazy event
-- Default keymaps that are always set: https://github.com/LazyVim/LazyVim/blob/main/lua/lazyvim/config/keymaps.lua
-- Add any additional keymaps here
vim.keymap.set("i", "jk", "<ESC>", { noremap = true, desc = "Escape insert mode" })
vim.keymap.set("t", "<C-\\>", "<C-\\><C-n>", { noremap = true, desc = "Escape terminal mode" })
vim.keymap.set("n", "<leader>dT", vim.lsp.codelens.run, { noremap = true, desc = "Run codelens" })
vim.keymap.set(
  "n",
  "<leader>zt",
  "<cmd>UserPutCurrentTimestampToClipboard<CR>p",
  { noremap = true, desc = "Get local timestamp to clipboard and paste it" }
)
vim.keymap.set(
  "n",
  "<leader>zT",
  "<cmd>UserPutPKMSFileDateTimestampToClipboard<CR>p",
  { noremap = true, desc = "Get local date timestamp to clipboard and paste it" }
)
