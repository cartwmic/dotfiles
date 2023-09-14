-- Keymaps are automatically loaded on the VeryLazy event
-- Default keymaps that are always set: https://github.com/LazyVim/LazyVim/blob/main/lua/lazyvim/config/keymaps.lua
-- Add any additional keymaps here
vim.keymap.set("i", "jk", "<ESC>", { noremap = true, desc = "Escape insert mode" })
vim.keymap.set("t", "<C-\\>", "<C-\\><C-n>", { noremap = true, desc = "Escape terminal mode" })
