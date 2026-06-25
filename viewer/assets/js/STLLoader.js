/**
 * STLLoader for Three.js r160
 * Ported from three/examples/jsm/loaders/STLLoader.js
 * Supports ASCII and binary STL files.
 */

import {
    BufferGeometry,
    FileLoader,
    Float32BufferAttribute,
    Loader,
} from 'three';

class STLLoader extends Loader {

    constructor( manager ) {
        super( manager );
    }

    load( url, onLoad, onProgress, onError ) {
        const scope = this;
        const loader = new FileLoader( this.manager );
        loader.setPath( this.path );
        loader.setResponseType( 'arraybuffer' );
        loader.setRequestHeader( this.requestHeader );
        loader.setWithCredentials( this.withCredentials );
        loader.load( url, function ( buffer ) {
            try {
                onLoad( scope.parse( buffer ) );
            } catch ( e ) {
                if ( onError ) {
                    onError( e );
                } else {
                    console.error( e );
                }
                scope.manager.itemError( url );
            }
        }, onProgress, onError );
    }

    parse( data ) {
        const binData = this._ensureBinary( data );
        return this._isBinary( binData )
            ? this._parseBinary( binData )
            : this._parseASCII( this._ensureString( data ) );
    }

    _isBinary( data ) {
        const expect = 80 + Uint32Array.BYTES_PER_ELEMENT;
        if ( data.byteLength <= expect ) return false;

        const numFaces  = new DataView( data ).getUint32( 80, true );
        const dataSize  = data.byteLength - expect;
        const faceSize  = ( 12 * 4 ) + 2; // 3 floats normal + 9 floats verts + uint16 attr
        if ( dataSize === numFaces * faceSize ) return true;

        // Fallback: ASCII STLs start with 'solid'
        const head = new Uint8Array( data, 0, Math.min( 5, data.byteLength ) );
        const solid = [ 115, 111, 108, 105, 100 ]; // 'solid'
        for ( let i = 0; i < solid.length; i++ ) {
            if ( head[ i ] !== solid[ i ] ) return true;
        }
        return false;
    }

    _parseBinary( data ) {
        const reader    = new DataView( data );
        const numFaces  = reader.getUint32( 80, true );
        const dataOffset = 84;
        const faceLength = ( 12 * 4 ) + 2;

        const vertices = new Float32Array( numFaces * 3 * 3 );
        const normals  = new Float32Array( numFaces * 3 * 3 );

        // Detect Magics color header
        let hasColors = false, colors;
        let defaultR = 1, defaultG = 1, defaultB = 1;
        for ( let i = 0; i < 80 - 10; i++ ) {
            if ( reader.getUint32( i, false ) === 0x434F4C4F &&
                 reader.getUint8( i + 4 ) === 0x52 &&
                 reader.getUint8( i + 5 ) === 0x3D ) {
                hasColors = true;
                colors    = new Float32Array( numFaces * 3 * 3 );
                defaultR  = reader.getUint8( i + 6 ) / 255;
                defaultG  = reader.getUint8( i + 7 ) / 255;
                defaultB  = reader.getUint8( i + 8 ) / 255;
                break;
            }
        }

        for ( let face = 0; face < numFaces; face++ ) {
            const base = dataOffset + face * faceLength;
            const nx   = reader.getFloat32( base,      true );
            const ny   = reader.getFloat32( base + 4,  true );
            const nz   = reader.getFloat32( base + 8,  true );

            let r = defaultR, g = defaultG, b = defaultB;
            if ( hasColors ) {
                const packed = reader.getUint16( base + 48, true );
                if ( ( packed & 0x8000 ) === 0 ) {
                    r = (  packed        & 0x1F ) / 31;
                    g = ( ( packed >> 5 ) & 0x1F ) / 31;
                    b = ( ( packed >> 10) & 0x1F ) / 31;
                }
            }

            for ( let v = 0; v < 3; v++ ) {
                const idx   = face * 9 + v * 3;
                const vbase = base + 12 + v * 12;
                vertices[ idx ]     = reader.getFloat32( vbase,     true );
                vertices[ idx + 1 ] = reader.getFloat32( vbase + 4, true );
                vertices[ idx + 2 ] = reader.getFloat32( vbase + 8, true );
                normals[ idx ]     = nx;
                normals[ idx + 1 ] = ny;
                normals[ idx + 2 ] = nz;
                if ( hasColors ) {
                    colors[ idx ]     = r;
                    colors[ idx + 1 ] = g;
                    colors[ idx + 2 ] = b;
                }
            }
        }

        const geo = new BufferGeometry();
        geo.setAttribute( 'position', new Float32BufferAttribute( vertices, 3 ) );
        geo.setAttribute( 'normal',   new Float32BufferAttribute( normals,  3 ) );
        if ( hasColors ) {
            geo.setAttribute( 'color', new Float32BufferAttribute( colors, 3 ) );
            geo.hasColors = true;
        }
        return geo;
    }

    _parseASCII( text ) {
        const patternFace   = /facet([\s\S]*?)endfacet/g;
        const patternNormal = /normal\s+([\d.eE+\-]+)\s+([\d.eE+\-]+)\s+([\d.eE+\-]+)/;
        const patternVertex = /vertex\s+([\d.eE+\-]+)\s+([\d.eE+\-]+)\s+([\d.eE+\-]+)/g;

        const vertices = [];
        const normals  = [];
        let m;

        while ( ( m = patternFace.exec( text ) ) !== null ) {
            const face    = m[ 0 ];
            const nMatch  = patternNormal.exec( face );
            const nx = nMatch ? parseFloat( nMatch[ 1 ] ) : 0;
            const ny = nMatch ? parseFloat( nMatch[ 2 ] ) : 0;
            const nz = nMatch ? parseFloat( nMatch[ 3 ] ) : 0;

            let vMatch;
            while ( ( vMatch = patternVertex.exec( face ) ) !== null ) {
                vertices.push(
                    parseFloat( vMatch[ 1 ] ),
                    parseFloat( vMatch[ 2 ] ),
                    parseFloat( vMatch[ 3 ] )
                );
                normals.push( nx, ny, nz );
            }
        }

        const geo = new BufferGeometry();
        geo.setAttribute( 'position', new Float32BufferAttribute( vertices, 3 ) );
        if ( normals.length > 0 ) {
            geo.setAttribute( 'normal', new Float32BufferAttribute( normals, 3 ) );
        } else {
            geo.computeVertexNormals();
        }
        return geo;
    }

    _ensureBinary( data ) {
        if ( typeof data === 'string' ) {
            const buf = new Uint8Array( data.length );
            for ( let i = 0; i < data.length; i++ ) buf[ i ] = data.charCodeAt( i ) & 0xff;
            return buf.buffer;
        }
        return data;
    }

    _ensureString( data ) {
        return typeof data === 'string' ? data : new TextDecoder().decode( data );
    }
}

export { STLLoader };
