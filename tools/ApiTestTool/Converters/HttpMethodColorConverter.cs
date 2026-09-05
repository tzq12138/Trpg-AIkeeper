using System;
using System.Globalization;
using System.Windows.Data;
using System.Windows.Media;

namespace ApiTestTool.Converters;

/// <summary>
/// Converts HTTP method to a color for visual identification.
/// </summary>
public class HttpMethodColorConverter : IValueConverter
{
    public object Convert(object value, Type targetType, object parameter, CultureInfo culture)
    {
        var method = value?.ToString()?.ToUpper() ?? "";
        return method switch
        {
            "GET" => new SolidColorBrush(Color.FromRgb(76, 175, 80)),     // Green
            "POST" => new SolidColorBrush(Color.FromRgb(33, 150, 243)),    // Blue
            "PATCH" => new SolidColorBrush(Color.FromRgb(255, 152, 0)),    // Orange
            "DELETE" => new SolidColorBrush(Color.FromRgb(244, 67, 54)),   // Red
            "WS" => new SolidColorBrush(Color.FromRgb(156, 39, 176)),       // Purple
            _ => new SolidColorBrush(Color.FromRgb(158, 158, 158)),        // Gray
        };
    }

    public object ConvertBack(object value, Type targetType, object parameter, CultureInfo culture)
        => throw new NotImplementedException();
}
