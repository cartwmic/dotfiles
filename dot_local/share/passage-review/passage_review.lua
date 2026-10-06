-- Neovim front end for passage-review.
--
-- Read a frozen snapshot in Neovim, visually select lines or text, press
-- `<leader>zc`, write a comment, and `:w`. Each comment becomes a pending passage-review note.
-- All storage goes through the adjacent passage_review.py CLI.
--
-- Loaded by `passage-review new|open` when $VISUAL/$EDITOR is nvim, and by
-- ~/.config/nvim/plugin/passage_review.lua for :PassageReview in any buffer.

local M = {}

local ns = vim.api.nvim_create_namespace("passage_review")
local script = debug.getinfo(1, "S").source:sub(2):gsub("%.lua$", ".py")

vim.api.nvim_set_hl(0, "PassageReviewQuote", { default = true, link = "DiffChange" })
vim.api.nvim_set_hl(0, "PassageReviewComment", { default = true, link = "DiagnosticVirtualTextInfo" })
vim.api.nvim_set_hl(0, "PassageReviewSign", { default = true, link = "DiagnosticSignInfo" })

local function notify(message, level)
  vim.notify(message, level or vim.log.levels.INFO, { title = "passage-review" })
end

local function cli(args, stdin)
  local command = vim.list_extend({ "python3", script }, args)
  local result = vim.system(command, { text = true, stdin = stdin }):wait()
  if result.code ~= 0 then
    error(vim.trim(result.stderr ~= "" and result.stderr or result.stdout), 0)
  end
  return result.stdout
end

-- Byte offset in `text` (0-based) -> 0-based row/col relative to the range start.
local function position(text, offset)
  local row, col = 0, offset
  for line in text:gmatch("([^\n]*)\n") do
    if col <= #line then
      break
    end
    col = col - #line - 1
    row = row + 1
  end
  return row, col
end

local function render(buf)
  local ok, out = pcall(cli, { "show", vim.b[buf].passage_review_id })
  if not ok then
    notify(out, vim.log.levels.ERROR)
    return
  end
  local data = vim.json.decode(out)
  local line_count = vim.api.nvim_buf_line_count(buf)
  vim.api.nvim_buf_clear_namespace(buf, ns, 0, -1)
  for _, note in ipairs(data.notes) do
    local first, last = note.line_start - 1, math.min(note.line_end, line_count) - 1
    for row = first, last do
      vim.api.nvim_buf_set_extmark(buf, ns, row, 0, { sign_text = "✎", sign_hl_group = "PassageReviewSign" })
    end
    -- Highlight the exact quote inside the anchored lines.
    local passage = table.concat(vim.api.nvim_buf_get_lines(buf, first, last + 1, false), "\n") .. "\n"
    local quote = note.quote:gsub("\n$", "")
    local start = quote ~= "" and passage:find(quote, 1, true)
    if start then
      local srow, scol = position(passage, start - 1)
      local erow, ecol = position(passage, start - 1 + #quote)
      vim.api.nvim_buf_set_extmark(buf, ns, first + srow, scol, {
        end_row = first + erow,
        end_col = ecol,
        hl_group = "PassageReviewQuote",
        strict = false,
      })
    end
    -- Wrap comments to the window so narrow (phone) terminals show all of them.
    local win = vim.fn.bufwinid(buf)
    local width = math.max(20, (win ~= -1 and vim.api.nvim_win_get_width(win) or 80) - 10)
    local virt_lines = { { { "  ✎ " .. note.note_id, "PassageReviewSign" } } }
    for _, paragraph in ipairs(vim.split(vim.trim(note.comment), "\n")) do
      local rest = paragraph
      repeat
        local piece = vim.fn.strcharpart(rest, 0, width)
        if vim.fn.strchars(rest) > width then
          local cut = piece:match("^.*()%s")
          if cut and cut > 1 then
            piece = piece:sub(1, cut - 1)
          end
        end
        rest = vim.trim(rest:sub(#piece + 1))
        virt_lines[#virt_lines + 1] = { { "    " .. piece, "PassageReviewComment" } }
      until rest == ""
    end
    vim.api.nvim_buf_set_extmark(buf, ns, last, 0, { virt_lines = virt_lines })
  end
end

-- The comment is drafted in a real temporary Markdown file, so the whole
-- Neovim config (completion, spelling, linting, formatting) works as usual.
-- Every :w saves the draft as a pending note; later writes replace that note.
-- md-render.nvim support: its rendered view of a review is a separate buffer.
-- Map rendered lines back to snapshot lines so comments work there too.
local function md_session(buf)
  if not vim.b[buf].md_render then
    return nil
  end
  local ok, preview = pcall(require, "md-render.preview")
  local session = ok and type(preview._sessions) == "table" and preview._sessions[buf] or nil
  local source = session and session.source_bufnr
  if source and vim.api.nvim_buf_is_valid(source) and vim.b[source].passage_review_id then
    return session
  end
end

local function render_views(source)
  local ok, preview = pcall(require, "md-render.preview")
  if not ok or type(preview._sessions) ~= "table" then
    return
  end
  for view, session in pairs(preview._sessions) do
    if session.source_bufnr == source and vim.api.nvim_buf_is_valid(view) then
      M.render_view(view)
    end
  end
end

local open_comment

function M.render_view(view)
  local session = md_session(view)
  local map = session and session.content and session.content.source_line_map
  if not map then
    return
  end
  local ok, out = pcall(cli, { "show", vim.b[session.source_bufnr].passage_review_id })
  if not ok then
    return
  end
  vim.api.nvim_buf_clear_namespace(view, ns, 0, -1)
  local line_count = vim.api.nvim_buf_line_count(view)
  for _, note in ipairs(vim.json.decode(out).notes) do
    local last
    for row = 1, math.min(#map, line_count) do
      if map[row] and map[row] >= note.line_start and map[row] <= note.line_end then
        vim.api.nvim_buf_set_extmark(view, ns, row - 1, 0, { sign_text = "✎", sign_hl_group = "PassageReviewSign" })
        last = row
      end
    end
    if last then
      local virt_lines = { { { "  ✎ " .. note.note_id, "PassageReviewSign" } } }
      for _, line in ipairs(vim.split(vim.trim(note.comment), "\n")) do
        virt_lines[#virt_lines + 1] = { { "    " .. line, "PassageReviewComment" } }
      end
      vim.api.nvim_buf_set_extmark(view, ns, last - 1, 0, { virt_lines = virt_lines })
    end
  end
end

local function comment_rendered(view)
  local session = md_session(view)
  if not session then
    return
  end
  local mode = vim.fn.mode()
  local p1, p2 = vim.fn.getpos("v"), vim.fn.getpos(".")
  if mode ~= "v" and mode ~= "V" then
    p1 = p2
  end
  local map = session.content.source_line_map or {}
  local first, last
  for row = math.min(p1[2], p2[2]), math.max(p1[2], p2[2]) do
    local line = map[row]
    if line and line > 0 then
      first, last = math.min(first or line, line), math.max(last or line, line)
    end
  end
  local selected = mode == "v" and vim.trim(table.concat(vim.fn.getregion(p1, p2, { type = "v" }), "\n")) or ""
  if mode == "v" or mode == "V" then
    vim.api.nvim_feedkeys(vim.keycode("<Esc>"), "nx", false)
  end
  if not first then
    return notify("No source lines under the selection.", vim.log.levels.WARN)
  end
  -- Keep an exact quote when the rendered text appears verbatim in the source.
  local source = table.concat(vim.api.nvim_buf_get_lines(session.source_bufnr, first - 1, last, false), "\n")
  local quote = selected ~= "" and source:find(selected, 1, true) and selected or nil
  open_comment(session.source_bufnr, first, last, quote)
end

local function attach_view(view)
  if not md_session(view) then
    return
  end
  local session = md_session(view)
  if not session._passage_review_rebuild then
    -- A rebuild (re-wrap on resize, zen, live edit) replaces every line and
    -- leaves our marks on the wrong rows. Redraw the comments after it.
    local rebuild = session.rebuild
    session._passage_review_rebuild = rebuild
    session.rebuild = function(self, ...)
      local results = { rebuild(self, ...) }
      vim.schedule(function()
        if vim.api.nvim_buf_is_valid(view) then
          M.render_view(view)
        end
      end)
      return unpack(results)
    end
  end
  M.render_view(view)
end

vim.api.nvim_create_autocmd({ "BufWinEnter", "WinResized" }, {
  group = vim.api.nvim_create_augroup("passage_review_md_render", { clear = true }),
  callback = function()
    vim.schedule(function()
      for _, win in ipairs(vim.api.nvim_tabpage_list_wins(0)) do
        attach_view(vim.api.nvim_win_get_buf(win))
      end
    end)
  end,
})

function open_comment(buf, first, last, quote)
  local id = vim.b[buf].passage_review_id
  local excerpt = vim.trim((quote or vim.api.nvim_buf_get_lines(buf, first - 1, first, false)[1] or ""):gsub("%s+", " "))
  if vim.fn.strchars(excerpt) > 40 then
    excerpt = vim.fn.strcharpart(excerpt, 0, 39) .. "…"
  end

  local path = vim.fn.tempname() .. ".md"
  local title = (" Lines %d-%d “%s” · :w saves the note"):format(first, last, excerpt)
  local from = vim.api.nvim_get_current_win()
  local float = vim.api.nvim_win_get_config(from)
  if float.relative ~= "" then
    -- From a floating window (for example zen mode), a split would land behind
    -- it and close it. Open the comment as a float on top instead; closing it
    -- returns to the window it came from.
    local width, height = vim.api.nvim_win_get_width(from), vim.api.nvim_win_get_height(from)
    local h = math.min(8, math.max(3, height - 4))
    local scratch = vim.api.nvim_create_buf(false, true)
    vim.bo[scratch].bufhidden = "wipe"
    vim.api.nvim_open_win(scratch, true, {
      relative = "win",
      win = from,
      row = height - h - 2,
      col = 0,
      width = math.max(20, width - 2),
      height = h,
      border = "rounded",
      title = title,
      zindex = (float.zindex or 50) + 10,
    })
    vim.cmd.edit(vim.fn.fnameescape(path))
  else
    vim.cmd("botright 8split " .. vim.fn.fnameescape(path))
    vim.wo.winbar = title
  end
  local cbuf = vim.api.nvim_get_current_buf()

  local group = vim.api.nvim_create_augroup("passage_review_comment_" .. cbuf, { clear = true })
  vim.api.nvim_create_autocmd("BufWritePost", {
    group = group,
    buffer = cbuf,
    callback = function()
      local text = table.concat(vim.fn.readfile(path), "\n") .. "\n"
      if vim.trim(text) == "" then
        return notify("Blank comment; no note saved.", vim.log.levels.WARN)
      end
      local args = { "note", id, "--lines", first .. "-" .. last }
      if quote then
        vim.list_extend(args, { "--quote", quote })
      end
      local ok, out = pcall(cli, args, text)
      if not ok then
        return notify("Not saved: " .. out, vim.log.levels.ERROR)
      end
      local previous = vim.b[cbuf].passage_review_note
      local note = vim.trim(out)
      vim.b[cbuf].passage_review_note = note
      if previous then
        pcall(cli, { "delete", id, "--note", previous })
        notify("Updated note " .. note)
      else
        notify("Saved pending note " .. note)
      end
      if vim.api.nvim_buf_is_valid(buf) then
        render(buf)
        render_views(buf)
      end
    end,
  })
  vim.api.nvim_create_autocmd({ "BufWipeout", "BufDelete" }, {
    group = group,
    buffer = cbuf,
    once = true,
    callback = function()
      vim.fn.delete(path)
    end,
  })
  vim.api.nvim_create_autocmd("VimLeavePre", { group = group, once = true, callback = function() vim.fn.delete(path) end })
  vim.cmd.startinsert()
end

local function comment_selection(buf)
  local mode = vim.fn.mode()
  local p1, p2 = vim.fn.getpos("v"), vim.fn.getpos(".")
  local first, last = math.min(p1[2], p2[2]), math.max(p1[2], p2[2])
  local quote
  if mode == "v" then
    quote = table.concat(vim.fn.getregion(p1, p2, { type = "v" }), "\n")
    if vim.trim(quote) == "" then
      quote = nil
    end
  end
  vim.api.nvim_feedkeys(vim.keycode("<Esc>"), "nx", false)
  open_comment(buf, first, last, quote)
end

local function attach(buf, data)
  vim.b[buf].passage_review_id = data.review_id
  vim.bo[buf].readonly = true
  vim.bo[buf].modifiable = false
  vim.bo[buf].filetype = vim.filetype.match({ filename = data.title }) or "markdown"
  vim.b[buf].passage_review_title = data.title
  M.refresh_header()
  render(buf)
end

--- Open (or attach to) the snapshot for an existing review ID.
function M.open(review_id)
  local ok, out = pcall(cli, { "show", review_id })
  if not ok then
    return notify(out, vim.log.levels.ERROR)
  end
  local data = vim.json.decode(out)
  if vim.fs.normalize(vim.api.nvim_buf_get_name(0)) ~= vim.fs.normalize(data.snapshot_path) then
    vim.cmd.edit(vim.fn.fnameescape(data.snapshot_path))
  end
  attach(vim.api.nvim_get_current_buf(), data)
end

--- Saved reviews of `path` that still have pending notes, newest first.
local function pending_reviews_of(path)
  local ok, listing = pcall(cli, { "list" })
  if not ok then
    return {}
  end
  local found = {}
  for line in listing:gmatch("[^\n]+") do
    local id, pending, created = line:match("^(rv%-%x+)\t.-\t(%d+) pending\t(.*)$")
    if id and tonumber(pending) > 0 then
      local shown, out = pcall(cli, { "show", id })
      local data = shown and vim.json.decode(out) or nil
      if data and data.source.kind == "file" and vim.fs.normalize(data.source.reference) == path then
        table.insert(found, { id = id, pending = tonumber(pending), created = created, snapshot = data.snapshot_path })
      end
    end
  end
  table.sort(found, function(a, b)
    return a.created > b.created
  end)
  return found
end

--- Freeze the current buffer as a new review and open it for commenting.
local function new_review(buf, as_file)
  local name = vim.api.nvim_buf_get_name(buf)
  local args, stdin
  if as_file then
    args = { "new", "--file", name, "--no-open" }
  else
    local title = name ~= "" and vim.fn.fnamemodify(name, ":t") or "[No Name]"
    args = { "new", "--title", title, "--no-open" }
    stdin = table.concat(vim.api.nvim_buf_get_lines(buf, 0, -1, false), "\n") .. "\n"
  end
  local ok, out = pcall(cli, args, stdin)
  if not ok then
    return notify(out, vim.log.levels.ERROR)
  end
  M.open(vim.trim(out))
end

local function remove_review(id)
  local ok, err = pcall(cli, { "remove", id })
  if not ok then
    return notify(err, vim.log.levels.ERROR)
  end
  -- Close buffers still showing the deleted snapshot (and md-render views of them).
  for _, b in ipairs(vim.api.nvim_list_bufs()) do
    local session = md_session(b)
    if vim.b[b].passage_review_id == id or (session and vim.b[session.source_bufnr].passage_review_id == id) then
      pcall(vim.api.nvim_buf_delete, b, { force = true })
    end
  end
  notify("Deleted review " .. id)
end

local function confirm_remove(review, after)
  vim.ui.select({ "Delete", "Cancel" }, {
    prompt = ("Delete review %s (%s%s pending)? Notes and exports go too."):format(
      review.id, review.title and (review.title .. ", ") or "", review.pending),
  }, function(choice)
    if choice == "Delete" then
      remove_review(review.id)
    end
    if after then
      after()
    end
  end)
end

--- Review the current buffer. A saved file that already has reviews with
--- pending notes asks first: reopen one, delete one, or start a new review.
function M.review_current()
  local buf = vim.api.nvim_get_current_buf()
  if vim.b[buf].passage_review_id then
    return notify("This buffer is already review " .. vim.b[buf].passage_review_id)
  end
  local name = vim.api.nvim_buf_get_name(buf)
  local as_file = name ~= "" and vim.bo[buf].buftype == "" and not vim.bo[buf].modified and vim.uv.fs_stat(name) ~= nil
  local path = as_file and vim.fs.normalize(vim.uv.fs_realpath(name) or name)
  local existing = as_file and pending_reviews_of(path) or {}
  if #existing == 0 then
    return new_review(buf, as_file)
  end

  local function pick(reviews)
    local current = table.concat(vim.api.nvim_buf_get_lines(buf, 0, -1, false), "\n") .. "\n"
    local choices = {}
    for _, review in ipairs(reviews) do
      local snapshot = table.concat(vim.fn.readfile(review.snapshot, "b"), "\n")
      local detail = ("%s · %d pending · %s%s"):format(
        review.id,
        review.pending,
        review.created:sub(1, 16):gsub("T", " "),
        snapshot ~= current and snapshot .. "\n" ~= current and " · file changed since" or ""
      )
      table.insert(choices, { action = "open", review = review, label = "Reopen " .. detail })
    end
    table.insert(choices, { action = "new", label = "Start a new review" })
    for _, review in ipairs(reviews) do
      table.insert(choices, { action = "delete", review = review, label = "Delete " .. review.id })
    end
    vim.ui.select(choices, {
      prompt = "This file has a review with pending notes",
      format_item = function(item)
        return item.label
      end,
    }, function(choice)
      if not choice then
        return
      elseif choice.action == "open" then
        M.open(choice.review.id)
      elseif choice.action == "new" then
        new_review(buf, as_file)
      else
        -- After deleting (or cancelling), come back to the same choice.
        confirm_remove(choice.review, function()
          vim.schedule(function()
            pick(pending_reviews_of(path))
          end)
        end)
      end
    end)
  end
  pick(existing)
end

--- Delete a saved review. With no ID, pick one (the current review first).
function M.delete(id)
  local ok, listing = pcall(cli, { "list" })
  if not ok then
    return notify(listing, vim.log.levels.ERROR)
  end
  local reviews = {}
  for line in listing:gmatch("[^\n]+") do
    local rid, title, pending, created = line:match("^(rv%-%x+)\t(.-)\t(%d+) pending\t(.*)$")
    if rid then
      table.insert(reviews, { id = rid, title = title, pending = pending, created = created })
    end
  end
  if id and id ~= "" then
    for _, review in ipairs(reviews) do
      if review.id == id then
        return confirm_remove(review)
      end
    end
    return notify("No review " .. id, vim.log.levels.WARN)
  end
  if #reviews == 0 then
    return notify("No saved reviews.")
  end
  local session = md_session(vim.api.nvim_get_current_buf())
  local current = vim.b.passage_review_id or (session and vim.b[session.source_bufnr].passage_review_id)
  table.sort(reviews, function(a, b)
    if (a.id == current) ~= (b.id == current) then
      return a.id == current
    end
    return a.created > b.created
  end)
  vim.ui.select(reviews, {
    prompt = "Delete which review?",
    format_item = function(r)
      return ("%s%s · %s · %s pending · %s"):format(
        r.id == current and "(current) " or "", r.id, r.title, r.pending, r.created:sub(1, 16):gsub("T", " "))
    end,
  }, function(choice)
    if choice then
      confirm_remove(choice)
    end
  end)
end

--- The review source buffer behind `buf`: the buffer itself, or the source of
--- an md-render view of it.
local function review_source(buf)
  if vim.b[buf].passage_review_id then
    return buf
  end
  local session = md_session(buf)
  return session and session.source_bufnr or nil
end

--- Show the review header on the current window when it shows a review (source
--- or rendered), and remove it when the window has moved on to something else.
--- Window-local, so it has to follow buffer swaps (md-render toggles, zen).
function M.refresh_header()
  local win = vim.api.nvim_get_current_win()
  local source = review_source(vim.api.nvim_win_get_buf(win))
  if source then
    local header = (" %s · <leader>zc comments on the selection or line"):format(
      vim.b[source].passage_review_title or vim.b[source].passage_review_id)
    if vim.wo[win].winbar ~= header then
      vim.wo[win].winbar = header
    end
    vim.w[win].passage_review_header = true
  elseif vim.w[win].passage_review_header then
    vim.wo[win].winbar = ""
    vim.w[win].passage_review_header = nil
  end
end

--- <leader>zc: comment on the selection or line in a review, source or rendered.
--- Global rather than buffer-local, so it keeps working when md-render or zen
--- swap buffers and windows underneath.
local function comment_here()
  local buf = vim.api.nvim_get_current_buf()
  if md_session(buf) then
    return comment_rendered(buf)
  elseif vim.b[buf].passage_review_id then
    local mode = vim.fn.mode()
    if mode == "v" or mode == "V" or mode == "\22" then
      return comment_selection(buf)
    end
    local row = vim.api.nvim_win_get_cursor(0)[1]
    return open_comment(buf, row, row, nil)
  end
  notify("Not a passage-review buffer (open one with :PassageReview).", vim.log.levels.WARN)
end

function M.setup()
  vim.keymap.set({ "n", "x" }, "<leader>zc", comment_here, { desc = "passage-review: comment on selection or line" })
  vim.api.nvim_create_autocmd({ "BufWinEnter", "WinEnter", "SafeState" }, {
    group = vim.api.nvim_create_augroup("passage_review_header", { clear = true }),
    callback = function()
      pcall(M.refresh_header)
    end,
  })
  vim.api.nvim_create_user_command("PassageReviewDelete", function(opts)
    M.delete(opts.args)
  end, { nargs = "?", desc = "passage-review: delete a saved review (pick one, or give its ID)" })
  vim.api.nvim_create_user_command("PassageReview", function(opts)
    if opts.args ~= "" then
      M.open(opts.args)
    else
      M.review_current()
    end
  end, { nargs = "?", desc = "passage-review: snapshot this buffer, or open a review ID" })
end

M.setup()
return M
