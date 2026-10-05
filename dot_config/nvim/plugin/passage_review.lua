-- :PassageReview — comment on any buffer with passage-review.
-- The module ships with the passage-review CLI (chezmoi dot_local/share/passage-review).
local module = vim.fn.expand("~/.local/share/passage-review/passage_review.lua")
if vim.uv.fs_stat(module) then
  dofile(module)
end
