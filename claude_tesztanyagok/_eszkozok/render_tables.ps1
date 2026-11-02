$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
$sampleRoot = if ($PSScriptRoot) { Split-Path -Parent $PSScriptRoot } else { Join-Path (Get-Location) 'claude_tesztanyagok' }
$specs = Get-Content -LiteralPath (Join-Path $sampleRoot '_eszkozok/image_specs.json') -Encoding UTF8 -Raw | ConvertFrom-Json
$font = New-Object System.Drawing.Font('Arial', 22, [System.Drawing.FontStyle]::Regular, [System.Drawing.GraphicsUnit]::Pixel)
$headerFont = New-Object System.Drawing.Font('Arial', 23, [System.Drawing.FontStyle]::Bold, [System.Drawing.GraphicsUnit]::Pixel)
$titleFont = New-Object System.Drawing.Font('Arial', 30, [System.Drawing.FontStyle]::Bold, [System.Drawing.GraphicsUnit]::Pixel)
$pen = New-Object System.Drawing.Pen([System.Drawing.Color]::Gray, 1)
$format = New-Object System.Drawing.StringFormat
$format.Alignment = [System.Drawing.StringAlignment]::Near
$format.LineAlignment = [System.Drawing.StringAlignment]::Center
foreach ($spec in $specs) {
    $wide = $spec.headers.Count -gt 7
    $width = if ($wide) { 2800 } else { 2100 }
    $widths = @()
    foreach ($header in $spec.headers) {
        $weight = switch ($header) {
            'Sorszám' { 0.4 }
            'Tárgy' { 3.0 }
            'Ajánlatkérő' { 2.3 }
            'Ajánlatkérő nevében eljár' { 1.8 }
            'Ajánlattételi határidő' { 1.6 }
            'Megjegyzés' { 1.6 }
            default { 1.3 }
        }
        $widths += $weight
    }
    $total = ($widths | Measure-Object -Sum).Sum
    $widths = @($widths | ForEach-Object { [single](($_ / $total) * ($width - 40)) })
    $rowHeight = if ($wide) { 145 } else { 125 }
    $height = 180 + ($rowHeight * $spec.rows.Count)
    $bitmap = New-Object System.Drawing.Bitmap($width, $height)
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    $graphics.Clear([System.Drawing.Color]::White)
    $graphics.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::AntiAliasGridFit
    $graphics.DrawString('FIKTÍV TESZTANYAG – nem valódi portál vagy hirdetmény', $titleFont, [System.Drawing.Brushes]::DarkRed, 20, 12)
    $graphics.DrawString([string]$spec.title, $headerFont, [System.Drawing.Brushes]::Black, 20, 58)
    $allRows = @(@{ values = $spec.headers; header = $true })
    foreach ($row in $spec.rows) { $allRows += @{ values = $row; header = $false } }
    $y = 105
    foreach ($row in $allRows) {
        $cellHeight = if ($row.header) { 65 } else { $rowHeight }
        $x = 20
        for ($column = 0; $column -lt $spec.headers.Count; $column++) {
            $rectangle = New-Object System.Drawing.RectangleF([single]$x, [single]$y, $widths[$column], [single]$cellHeight)
            if ($row.header) { $graphics.FillRectangle([System.Drawing.Brushes]::WhiteSmoke, $rectangle) }
            $graphics.DrawRectangle($pen, $rectangle.X, $rectangle.Y, $rectangle.Width, $rectangle.Height)
            $textRectangle = New-Object System.Drawing.RectangleF(([single]$x + 7), ([single]$y + 4), ($widths[$column] - 14), ([single]$cellHeight - 8))
            $selectedFont = if ($row.header) { $headerFont } else { $font }
            $graphics.DrawString([string]$row.values[$column], $selectedFont, [System.Drawing.Brushes]::Black, $textRectangle, $format)
            if ($spec.partial -and -not $row.header -and $y -eq 170 -and $spec.headers[$column] -eq 'Ajánlattételi határidő') {
                $graphics.FillRectangle([System.Drawing.Brushes]::White, $textRectangle)
            }
            $x += $widths[$column]
        }
        $y += $cellHeight
    }
    $target = Join-Path (Join-Path $sampleRoot '04_kepforrasok') $spec.filename
    if ($spec.partial) {
        $cropped = $bitmap.Clone((New-Object System.Drawing.Rectangle(0, 0, $width, ($height - 100))), $bitmap.PixelFormat)
        $cropped.Save($target, [System.Drawing.Imaging.ImageFormat]::Png)
        $cropped.Dispose()
    } else { $bitmap.Save($target, [System.Drawing.Imaging.ImageFormat]::Png) }
    $graphics.Dispose()
    $bitmap.Dispose()
}
$format.Dispose()
$pen.Dispose()
$font.Dispose()
$headerFont.Dispose()
$titleFont.Dispose()
Write-Output ('Elkészült képek: ' + $specs.Count)
