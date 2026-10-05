-- Browser-like Markdown view inside Neovim: tables, callouts, images and
-- Mermaid in a separate read-only rendered buffer; edit in the source. In a
-- plain kitty window (>= 0.40) headings are drawn larger with kitty's text
-- sizing protocol; inside Herdr they stay normal size. passage-review reviews
-- also accept <leader>zc comments in the rendered view.
--
-- Width: md-render caps text at 80 columns. Here the rendered text fills the
-- window instead, so zen mode (<leader>uz) sets the reading column.

-- md-render has no option for "follow the window"; set the width on its
-- session (internal fields) and mark it explicit so its own 80-column resize
-- handler stays out of the way.
--
-- Scaled headings (kitty text sizing) are painted for one window per session.
-- Zen shows the rendered buffer in a float, so move that painting to the
-- window in front: zen's float while it is open, the original after.
local function reattach_text_size(session, win)
  local text_size = require("md-render.text_size")
  if session.text_size_state then
    -- detach also forces a full redraw, which clears stale scaled glyphs.
    pcall(text_size.detach, session.text_size_state)
    session.text_size_state = nil
  end
  session.text_size_state = text_size.attach(win, session.content)
end

local function fit_render_windows()
  local ok, preview = pcall(require, "md-render.preview")
  if not ok or type(preview._sessions) ~= "table" then
    return
  end
  local current = vim.api.nvim_get_current_win()
  for buf, session in pairs(preview._sessions) do
    local win = vim.api.nvim_win_get_buf(current) == buf and current or vim.fn.bufwinid(buf)
    if win ~= -1 and vim.api.nvim_win_is_valid(win) then
      local changed = session.win ~= win
      session.win = win
      local info = vim.fn.getwininfo(win)[1]
      local width = math.max(20, vim.api.nvim_win_get_width(win) - (info and info.textoff or 0) - 2)
      session._explicit_max_width = true
      if session.opts.max_width ~= width then
        session.opts.max_width = width
        pcall(session.rebuild, session)
        changed = true
      end
      -- A rebuild or a window switch can leave headings plain-size or stale;
      -- start painting afresh in the window that is in front.
      if changed then
        pcall(reattach_text_size, session, win)
      end
    end
  end
end

-- Heading sizes: # at 3x, ## at 2x, the rest plain (bold, coloured, icon).
-- md-render's own ladder (2x, 1.75x, 1.5x ...) fakes in-between sizes with
-- chunked runs that leave gaps inside words; whole multiples have no gaps.
-- The level icon is scaled with its heading, so the icon gets room for a
-- double-width scaled glyph. All of this patches md-render internals and is
-- pinned by lazy-lock.json; recheck after updating the plugin.
local HEADING_SCALE = { [1] = 3, [2] = 2 }

local function scale_headings()
  local text_size = require("md-render.text_size")
  local markdown = require("md-render.markdown")

  local stock_spec = text_size.spec_for
  text_size.spec_for = function(level)
    local s = HEADING_SCALE[level]
    if not s or not stock_spec(level) then -- stock checks enabled + kitty support
      return nil
    end
    return { level = level, s = s, ratio = s }
  end

  -- Icon block is 2*s cells wide; one more cell separates it from the text.
  local stock_prefix = markdown.heading_icon_prefix
  markdown.heading_icon_prefix = function(level)
    local s = HEADING_SCALE[level]
    if s and text_size.spec_for(level) then
      local icon = markdown.heading_icon(level)
      return icon .. string.rep(" ", 2 * s + 1 - vim.api.nvim_strwidth(icon))
    end
    return stock_prefix(level)
  end

  -- md-render paints the icon at plain size ("s=S:n=1:d=S:w=1") and fills the
  -- block's lower rows from icon_col + S. Paint the icon scaled instead, two
  -- cells wide so the Nerd Font glyph is not clipped, and start the fill after it.
  local send = vim.api.nvim_ui_send
  vim.api.nvim_ui_send = function(data)
    if type(data) ~= "string" or not data:find("\27]66;s=%d+:n=1:d=%d+:w=1:") then
      return send(data)
    end
    local moves = {}
    data = data:gsub("\27%[(%d+);(%d+)H([\27%[%d;m]*)\27%]66;s=(%d+):n=1:d=%d+:w=1:v=%d+;", function(r, c, sgr, sc)
      r, c, sc = tonumber(r), tonumber(c), tonumber(sc)
      for i = 1, sc - 1 do
        moves[(r + i) .. ";" .. (c + sc)] = c + 2 * sc
      end
      return ("\27[%d;%dH%s\27]66;s=%d:w=2;"):format(r, c, sgr, sc)
    end)
    data = data:gsub("\27%[(%d+);(%d+)H", function(r, c)
      local to = moves[r .. ";" .. c]
      return to and ("\27[%s;%dH"):format(r, to) or nil
    end)
    return send(data)
  end
end

return {
  {
    "delphinus/md-render.nvim",
    version = "*",
    cmd = "MdRender",
    keys = {
      -- Global, not ft-scoped: md-render sets up its rendered buffer with
      -- autocmds suppressed, so a FileType-scoped key never reaches it.
      {
        "<leader>mr",
        function()
          if vim.b.md_render or vim.bo.filetype == "markdown" then
            require("md-render").preview.toggle()
          end
        end,
        desc = "Markdown: toggle rendered view",
      },
      { "<leader>ms", "<cmd>vertical MdRender split<cr>", ft = "markdown", desc = "Markdown: source + rendered split" },
      { "<leader>ma", "<cmd>MdRender auto toggle<cr>", ft = "markdown", desc = "Markdown: render outside Insert" },
      { "<leader>mf", "<Plug>(md-render-preview)", ft = "markdown", desc = "Markdown: floating preview" },
    },
    config = function()
      scale_headings()
      vim.api.nvim_create_autocmd({ "BufWinEnter", "WinEnter", "WinResized", "VimResized" }, {
        group = vim.api.nvim_create_augroup("md_render_fit_window", { clear = true }),
        callback = function()
          vim.schedule(fit_render_windows)
        end,
      })
      vim.schedule(fit_render_windows)
    end,
  },
  {
    "folke/which-key.nvim",
    optional = true,
    opts = { spec = { { "<leader>m", group = "markdown" } } },
  },
  -- Zen (<leader>uz) is the narrow reading column; headings follow it there.
  {
    "folke/snacks.nvim",
    opts = {
      zen = {
        win = { width = 90 },
        on_open = function()
          vim.schedule(fit_render_windows)
        end,
        on_close = function()
          vim.schedule(fit_render_windows)
        end,
      },
    },
  },
}
