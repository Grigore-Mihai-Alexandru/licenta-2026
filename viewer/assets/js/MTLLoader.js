/**
 * MTLLoader for Three.js r160
 * Parses Wavefront .mtl files and creates Three.js materials.
 * Supports: Kd/Ka/Ks colours, Ns shininess, d/Tr opacity, map_Kd texture,
 *           map_Bump/bump normal maps, map_Ks specular maps.
 */

import {
    Color,
    FileLoader,
    FrontSide,
    Loader,
    MeshPhongMaterial,
    RepeatWrapping,
    TextureLoader,
    Vector2,
} from 'three';

// ---------------------------------------------------------------------------
// MTLLoader
// ---------------------------------------------------------------------------

class MTLLoader extends Loader {

    constructor( manager ) { super( manager ); }

    setMaterialOptions( v ) { this.materialOptions = v; return this; }

    load( url, onLoad, onProgress, onError ) {
        const scope  = this;
        // derive base path from URL when setPath was not called explicitly
        const base   = this.path || _extractBase( url );
        const loader = new FileLoader( this.manager );
        loader.setPath( this.path );
        loader.setRequestHeader( this.requestHeader );
        loader.setWithCredentials( this.withCredentials );
        loader.load( url, function ( text ) {
            try { onLoad( scope.parse( text, base ) ); }
            catch ( e ) {
                if ( onError ) onError( e );
                else { console.error( e ); scope.manager.itemError( url ); }
            }
        }, onProgress, onError );
    }

    parse( text, basePath ) {
        const materialsInfo = {};
        let current = null;

        for ( const raw of text.split( '\n' ) ) {
            const line = raw.trim();
            if ( ! line || line[ 0 ] === '#' ) continue;
            const sp  = line.indexOf( ' ' );
            const key = ( sp >= 0 ? line.slice( 0, sp ) : line ).toLowerCase();
            const val = sp >= 0 ? line.slice( sp + 1 ).trim() : '';

            if ( key === 'newmtl' ) {
                current = {};
                materialsInfo[ val ] = current;
            } else if ( current ) {
                current[ key ] = val;
            }
        }

        const rp      = this.resourcePath || basePath || '';
        const creator = new MaterialCreator( rp, this.materialOptions || {} );
        creator.crossOrigin = this.crossOrigin;
        creator.manager     = this.manager;
        creator.setMaterials( materialsInfo );
        return creator;
    }
}

// ---------------------------------------------------------------------------
// MaterialCreator — called by OBJLoader via .create(materialName)
// ---------------------------------------------------------------------------

class MaterialCreator {

    constructor( baseUrl = '', options = {} ) {
        this.baseUrl       = _normalise( baseUrl );
        this.options       = options;
        this.materialsInfo = {};
        this.materials     = {};
        this.nameLookup    = {};
        this.crossOrigin   = 'anonymous';
        this.side          = options.side ?? FrontSide;
        this.wrap          = options.wrap ?? RepeatWrapping;
        this.manager       = undefined; // set by MTLLoader.parse
    }

    setMaterials( mi ) {
        this.materialsInfo = mi;
        this.materials     = {};
        this.nameLookup    = {};
        return this;
    }

    preload() {
        for ( const n of Object.keys( this.materialsInfo ) ) this.create( n );
    }

    getIndex( n ) { return this.nameLookup[ n ]; }

    getAsArray() {
        const arr = [];
        for ( const n of Object.keys( this.materialsInfo ) ) {
            arr.push( this.create( n ) );
            this.nameLookup[ n ] = arr.length - 1;
        }
        return arr;
    }

    create( name ) {
        if ( this.materials[ name ] === undefined )
            this.materials[ name ] = this._build( name );
        return this.materials[ name ];
    }

    // -- internals ----------------------------------------------------------

    _resolveUrl( url ) {
        if ( ! url ) return '';
        url = url.replace( /\\/g, '/' ).trim();
        if ( /^(https?:|file:|data:)/i.test( url ) ) return url;
        return this.baseUrl + url;
    }

    _loadTex( url ) {
        const loader = new TextureLoader( this.manager );
        loader.setCrossOrigin( this.crossOrigin );
        const tex = loader.load( this._resolveUrl( url ) );
        tex.wrapS = this.wrap;
        tex.wrapT = this.wrap;
        return tex;
    }

    _parseMapArgs( value ) {
        const parts  = value.trim().split( /\s+/ );
        let i = 0;
        let scale = null, offset = null;
        while ( i < parts.length ) {
            if ( parts[ i ] === '-s' && i + 2 < parts.length ) {
                scale = new Vector2( parseFloat( parts[ i + 1 ] ), parseFloat( parts[ i + 2 ] ) );
                i += 3;
            } else if ( parts[ i ] === '-o' && i + 2 < parts.length ) {
                offset = new Vector2( parseFloat( parts[ i + 1 ] ), parseFloat( parts[ i + 2 ] ) );
                i += 3;
            } else if ( parts[ i ].startsWith( '-' ) ) {
                i += 2; // unknown flag + value
            } else {
                return { url: parts.slice( i ).join( ' ' ), scale, offset };
            }
        }
        return { url: value.trim(), scale, offset };
    }

    _applyMap( params, key, raw ) {
        if ( ! raw ) return;
        const { url, scale, offset } = this._parseMapArgs( raw );
        if ( ! url ) return;
        const tex = this._loadTex( url );
        if ( scale )  tex.repeat.copy( scale );
        if ( offset ) tex.offset.copy( offset );
        params[ key ] = tex;
    }

    _rgb( str ) {
        const c = str.trim().split( /\s+/ ).map( parseFloat );
        return new Color( c[ 0 ] ?? 1, c[ 1 ] ?? 1, c[ 2 ] ?? 1 );
    }

    _build( name ) {
        const mat    = this.materialsInfo[ name ] || {};
        const params = { name, side: this.side };

        if ( mat.kd  ) params.color    = this._rgb( mat.kd );
        if ( mat.ks  ) params.specular = this._rgb( mat.ks );
        if ( mat.ns  !== undefined ) params.shininess = parseFloat( mat.ns );

        const d = mat.d  !== undefined ? parseFloat( mat.d )
                : mat.tr !== undefined ? 1 - parseFloat( mat.tr )
                : 1.0;
        if ( d < 1.0 ) { params.opacity = d; params.transparent = true; }

        // Texture maps — try common key variants written by exporters
        this._applyMap( params, 'map',        mat[ 'map_kd'   ] || mat[ 'map_kd ' ] );
        this._applyMap( params, 'specularMap', mat[ 'map_ks'   ] );
        this._applyMap( params, 'bumpMap',     mat[ 'map_bump' ] || mat[ 'bump' ]   );
        if ( mat[ 'bm' ] !== undefined ) params.bumpScale = parseFloat( mat[ 'bm' ] );

        return new MeshPhongMaterial( params );
    }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function _extractBase( url ) {
    const i = url.lastIndexOf( '/' );
    return i >= 0 ? url.slice( 0, i + 1 ) : '';
}

function _normalise( url ) {
    url = ( url || '' ).replace( /\\/g, '/' );
    if ( url && ! url.endsWith( '/' ) ) url += '/';
    return url;
}

export { MTLLoader };
